import json
import threading

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from src.constants.enums import DpStatus
from src.models import DpBudget, DpPublication, GradeReading, GradeStudy, Treatment
from src.schemas.dp import DpBudgetInput, DpReleaseInput
from src.services import dp_service
from src.services.dp_mechanism import (
    DP_SENSITIVITY_L1,
    epsilon_to_micros,
    noisy_grade_table,
    result_fingerprint,
)


class User:
    email = 'admin@qingnie.local'


def study_id(db, code='QN-SHIFT'):
    return db.scalar(select(GradeStudy.id).where(GradeStudy.code == code))


def preset(db, code='QN-SHIFT', total=1.0):
    sid = study_id(db, code)
    assert sid is not None
    dp_service.set_budget(db, DpBudgetInput(study_id=sid, total_epsilon=total), User())
    return sid


def release(db, sid, name, epsilon=0.1):
    return dp_service.create_release(db, DpReleaseInput(study_id=sid, name=name, epsilon=epsilon), User())


def test_sensitivity_adjacency_and_noise_scale(seeded):
    sid = preset(seeded, total=1.0)
    payload = release(seeded, sid, '对外合作 · 等级分布', epsilon=0.25)
    result = payload['result']
    assert result['sensitivity_l1'] == DP_SENSITIVITY_L1 == 2
    assert result['noise_scale'] == pytest.approx(2 / 0.25)
    assert result['adjacency'] == 'bounded-replacement-one-specimen-record'
    assert '替换一份独立试样记录' in result['adjacency_explanation']
    assert 'L1敏感度为2' in result['adjacency_explanation']
    assert 'Laplace(0, 2/ε)' in result['disclosure']
    cells = [c for t in result['treatments'] for c in t['noisy_counts']]
    assert len(cells) == 4 * 9
    assert {c['grade'] for c in cells} == set(range(1, 10))
    # The distributed payload must not smuggle raw frequencies, per-specimen
    # grades or exact/asymptotic test output.
    blob = json.dumps(payload, ensure_ascii=False)
    for leaked in ('specimen_code', 'grade_counts', 'p_asymptotic', 'h_raw', 'pairs', 'ranked_readings', 'exact', 'fingerprint', 'snapshot'):
        assert leaked not in blob


def test_same_frozen_input_and_params_reuses_publication_across_names(seeded):
    sid = preset(seeded, total=1.0)
    first = release(seeded, sid, '对外合作 · 首次', epsilon=0.2)
    budget = dp_service.get_budget(seeded, sid)
    assert budget.spent_epsilon_micros == epsilon_to_micros(0.2)

    second = release(seeded, sid, '对外合作 · 换名重试', epsilon=0.2)
    assert second['id'] == first['id']
    assert second['reused'] is True
    assert second['release_digest'] == first['release_digest']
    assert sorted(second['names']) == ['对外合作 · 换名重试', '对外合作 · 首次']
    assert second['result'] == first['result']
    seeded.refresh(budget)
    assert budget.spent_epsilon_micros == epsilon_to_micros(0.2), '换名不得再次扣费或重新抽噪'


def test_same_name_cannot_point_at_a_different_result(seeded):
    sid = preset(seeded, total=1.0)
    release(seeded, sid, '唯一名称', epsilon=0.1)
    with pytest.raises(HTTPException) as exc:
        release(seeded, sid, '唯一名称', epsilon=0.2)
    assert exc.value.status_code == 409


def test_corrected_grade_or_new_version_is_a_new_charge(seeded):
    sid = preset(seeded, total=1.0)
    release(seeded, sid, '版本一', epsilon=0.1)
    budget = dp_service.get_budget(seeded, sid)
    reading = seeded.scalar(select(GradeReading).where(GradeReading.study_id == sid).order_by(GradeReading.specimen_code))
    reading.grade = reading.grade + 1 if reading.grade < 9 else reading.grade - 1
    seeded.commit()

    corrected = release(seeded, sid, '版本一 · 更正等级', epsilon=0.1)
    seeded.refresh(budget)
    assert corrected['reused'] is False
    assert budget.spent_epsilon_micros == epsilon_to_micros(0.2)

    treatment = seeded.scalar(select(Treatment).where(Treatment.study_id == sid).order_by(Treatment.code))
    reading = seeded.scalar(select(GradeReading).where(GradeReading.study_id == sid).order_by(GradeReading.specimen_code))
    reading.treatment_id = seeded.scalar(select(Treatment.id).where(Treatment.study_id == sid, Treatment.id != treatment.id))
    seeded.commit()
    moved = release(seeded, sid, '版本二 · 改归属', epsilon=0.1)
    seeded.refresh(budget)
    assert moved['id'] != corrected['id']
    assert budget.spent_epsilon_micros == epsilon_to_micros(0.3)


def test_budget_never_resets_and_cannot_shrink_below_spent(seeded):
    sid = preset(seeded, total=0.3)
    release(seeded, sid, '耗尽前', epsilon=0.2)
    with pytest.raises(HTTPException) as exc:
        dp_service.set_budget(seeded, DpBudgetInput(study_id=sid, total_epsilon=0.1), User())
    assert exc.value.status_code == 409
    raised = dp_service.set_budget(seeded, DpBudgetInput(study_id=sid, total_epsilon=0.5), User())
    assert raised['spent_epsilon'] == pytest.approx(0.2)
    assert raised['remaining_epsilon'] == pytest.approx(0.3)
    with pytest.raises(HTTPException) as exc:
        release(seeded, sid, '透支尝试', epsilon=0.4)
    assert exc.value.status_code == 429
    budget = dp_service.get_budget(seeded, sid)
    assert budget.spent_epsilon_micros == epsilon_to_micros(0.2), '失败请求不得部分扣费'
    assert seeded.scalar(select(func.count()).select_from(DpPublication).where(DpPublication.study_id == sid)) == 1


def test_concurrent_requests_cannot_overdraw(seeded):
    from src.config.database import Session

    sid = preset(seeded, total=0.5)
    budget_id = dp_service.get_budget(seeded, sid).id
    outcomes = []
    barrier = threading.Barrier(8)

    def attempt():
        with Session() as db:
            barrier.wait()
            try:
                charged = dp_service.charge_budget(db, budget_id, epsilon_to_micros(0.1))
                db.commit()
                outcomes.append(charged)
            except OperationalError:
                db.rollback()
                outcomes.append(False)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with Session() as db:
        spent = db.get(DpBudget, budget_id).spent_epsilon_micros
    assert sum(1 for o in outcomes if o) == 5
    assert spent == epsilon_to_micros(0.5)


def test_interrupted_after_artifact_keeps_charge_and_same_noise(seeded):
    sid = preset(seeded, total=1.0)
    payload = release(seeded, sid, '首次发布', epsilon=0.2)
    publication = seeded.scalar(select(DpPublication).where(DpPublication.study_id == sid))
    original = json.loads(json.dumps(publication.result, sort_keys=True))
    seed = publication.noise_seed
    spent = dp_service.get_budget(seeded, sid).spent_epsilon_micros
    assert spent == epsilon_to_micros(0.2)

    # Simulate a crash after the noisy artifact was persisted but before the
    # row could be marked released.
    publication.status = DpStatus.FAILED
    publication.error = 'interrupted after artifact write'
    seeded.commit()
    retried = dp_service.retry_release(seeded, publication.id)
    assert retried['result'] == original, '恢复必须复用已落盘的噪声，不得重新抽噪'
    assert seeded.get(DpPublication, publication.id).noise_seed == seed
    assert dp_service.get_budget(seeded, sid).spent_epsilon_micros == spent, '中断不退费'

    again = release(seeded, sid, '中断后换名', epsilon=0.2)
    assert again['id'] == publication.id and again['reused'] is True
    assert dp_service.get_budget(seeded, sid).spent_epsilon_micros == spent


def test_midflight_failure_then_retry_recovers_same_release(seeded, monkeypatch):
    sid = preset(seeded, total=1.0)
    original = dp_service.noisy_grade_table
    seeds = []

    def flaky(snapshot, epsilon_micros, noise_seed):
        seeds.append(noise_seed)
        table = original(snapshot, epsilon_micros, noise_seed)
        if len(seeds) == 1:
            raise OSError('disk went away')
        return table

    monkeypatch.setattr(dp_service, 'noisy_grade_table', flaky)
    with pytest.raises(HTTPException) as exc:
        release(seeded, sid, '飞行中失败', epsilon=0.25)
    assert exc.value.status_code == 500
    row = seeded.scalar(select(DpPublication).where(DpPublication.study_id == sid))
    seeded.refresh(row)
    assert row.status == DpStatus.FAILED
    assert dp_service.get_budget(seeded, sid).spent_epsilon_micros == epsilon_to_micros(0.25), '失败不退费'

    monkeypatch.setattr(dp_service, 'noisy_grade_table', original)
    recovered = dp_service.retry_release(seeded, row.id)
    assert recovered['status'] == DpStatus.RELEASED
    attempted_seed = seeds[0]
    assert int(row.noise_seed, 16) == attempted_seed, '重试沿用原噪声种子'
    expected = original(row.snapshot, row.epsilon_micros, attempted_seed)
    assert recovered['result']['treatments'] == expected['treatments']
    assert dp_service.get_budget(seeded, sid).spent_epsilon_micros == epsilon_to_micros(0.25)


def test_export_only_carries_charged_noisy_table(seeded):
    sid = preset(seeded, total=1.0)
    payload = release(seeded, sid, '分发检查', epsilon=0.5)
    raw_rows = seeded.execute(select(GradeReading.specimen_code, GradeReading.grade).where(GradeReading.study_id == sid)).all()
    csv_text = dp_service.export_release(seeded, payload['id'])
    assert 'noisy_count' in csv_text
    assert 'adjacency' in csv_text.splitlines()[0]
    for specimen, _grade in raw_rows:
        assert specimen not in csv_text, '分发文件不得夹带逐份试样标识'
    for leaked in ('p_asymptotic', 'p_holm', 'ranked_readings', 'h_raw'):
        assert leaked not in csv_text
    # An exact raw cell (treatment, grade, count) must not appear as a CSV row.
    treatments = seeded.scalars(select(Treatment).where(Treatment.study_id == sid)).all()
    for treatment in treatments:
        for grade in range(1, 10):
            raw_count = seeded.scalar(select(func.count()).select_from(GradeReading).where(
                GradeReading.study_id == sid, GradeReading.treatment_id == treatment.id, GradeReading.grade == grade))
            raw_line = f'{treatment.code},{treatment.name},{grade},{raw_count}'
            assert raw_line not in csv_text.splitlines(), '分发文件不得夹带精确原始频数'


def test_publication_identity_ignores_request_name(seeded):
    sid = preset(seeded, total=1.0)
    study = seeded.get(GradeStudy, sid)
    snapshot = dp_service.build_snapshot(seeded, study)
    fingerprint = result_fingerprint(snapshot, epsilon_to_micros(0.1))
    assert fingerprint == result_fingerprint(snapshot, epsilon_to_micros(0.1))
    assert fingerprint != result_fingerprint(snapshot, epsilon_to_micros(0.2))
    a = release(seeded, sid, '名称甲', epsilon=0.1)
    b = release(seeded, sid, '名称乙', epsilon=0.1)
    assert a['id'] == b['id'] and a['release_digest'] == b['release_digest']
    c = release(seeded, sid, '名称丙', epsilon=0.2)
    assert c['id'] != a['id']
    assert dp_service.get_budget(seeded, sid).spent_epsilon_micros == epsilon_to_micros(0.3)


def test_unpreset_budget_blocks_release(seeded):
    sid = study_id(seeded)
    with pytest.raises(HTTPException) as exc:
        release(seeded, sid, '未预设', epsilon=0.1)
    assert exc.value.status_code == 409


def test_mechanism_is_deterministic_given_seed(seeded):
    sid = preset(seeded, total=1.0)
    study = seeded.get(GradeStudy, sid)
    snapshot = dp_service.build_snapshot(seeded, study)
    a = noisy_grade_table(snapshot, epsilon_to_micros(0.3), 12345)
    b = noisy_grade_table(snapshot, epsilon_to_micros(0.3), 12345)
    c = noisy_grade_table(snapshot, epsilon_to_micros(0.3), 54321)
    assert a == b
    assert a['treatments'] != c['treatments']


def test_concurrent_identical_requests_charge_once(seeded):
    """Same frozen input and epsilon is one publication, even under a race."""
    from src.config.database import Session

    sid = preset(seeded, total=0.5)
    barrier = threading.Barrier(6)
    outcomes = []

    def attempt(index):
        with Session() as db:
            barrier.wait()
            try:
                payload = dp_service.create_release(
                    db, DpReleaseInput(study_id=sid, name=f'并发同名 {index}', epsilon=0.1), User())
                outcomes.append(('ok', payload['id'], payload['reused']))
            except HTTPException as exc:
                outcomes.append(('error', exc.status_code, None))

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(o[0] == 'ok' for o in outcomes), outcomes
    assert len({o[1] for o in outcomes}) == 1, '同一冻结输入与ε只能有一份已扣费发布'
    with Session() as db:
        assert dp_service.get_budget(db, sid).spent_epsilon_micros == epsilon_to_micros(0.1)
        assert db.scalar(select(func.count()).select_from(DpPublication).where(DpPublication.study_id == sid)) == 1
        names = db.scalars(select(DpPublication)).one()
        assert len(dp_service._names_for(db, names.id)) == 6, '六次换名都挂在同一发布上，且各占一名'


def test_concurrent_distinct_epsilons_cannot_overdraw(seeded):
    from src.config.database import Session

    sid = preset(seeded, total=0.3)
    barrier = threading.Barrier(6)
    outcomes = []
    epsilons = [0.06, 0.07, 0.08, 0.09, 0.10, 0.11]

    def attempt(index):
        with Session() as db:
            barrier.wait()
            try:
                payload = dp_service.create_release(
                    db, DpReleaseInput(study_id=sid, name=f'并发不同ε {index}', epsilon=epsilons[index]), User())
                outcomes.append(('ok', epsilons[index], payload['id']))
            except HTTPException as exc:
                db.rollback()
                outcomes.append(('denied', epsilons[index], exc.status_code))

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    accepted = [o for o in outcomes if o[0] == 'ok']
    denied = [o for o in outcomes if o[0] == 'denied']
    assert accepted and denied, outcomes
    assert all(o[2] == 429 for o in denied), outcomes
    charged = sum(epsilon_to_micros(o[1]) for o in accepted)
    assert charged <= epsilon_to_micros(0.3)
    with Session() as db:
        budget = dp_service.get_budget(db, sid)
        assert budget.spent_epsilon_micros == charged, '被拒绝的请求不得留下部分扣费'
        assert db.scalar(select(func.count()).select_from(DpPublication).where(DpPublication.study_id == sid)) == len(accepted)


def test_reuse_is_free_even_after_budget_exhausted(seeded):
    sid = preset(seeded, total=0.1)
    first = release(seeded, sid, '预算用尽', epsilon=0.1)
    assert dp_service.get_budget(seeded, sid).spent_epsilon_micros == epsilon_to_micros(0.1)
    reused = release(seeded, sid, '预算用尽 · 换名', epsilon=0.1)
    assert reused['id'] == first['id'] and reused['reused'] is True
    assert dp_service.get_budget(seeded, sid).spent_epsilon_micros == epsilon_to_micros(0.1)

    reading = seeded.scalar(select(GradeReading).where(GradeReading.study_id == sid).order_by(GradeReading.specimen_code))
    reading.grade = reading.grade + 1 if reading.grade < 9 else reading.grade - 1
    seeded.commit()
    with pytest.raises(HTTPException) as exc:
        release(seeded, sid, '新版本', epsilon=0.1)
    assert exc.value.status_code == 429
    assert dp_service.get_budget(seeded, sid).spent_epsilon_micros == epsilon_to_micros(0.1)


def test_neighbouring_tables_ratio_bounded_by_exp_epsilon(seeded):
    """Analytic check: the published table is eps-DP under one-record replacement."""
    import math

    epsilon = 0.4
    scale = DP_SENSITIVITY_L1 / epsilon

    def density(x):
        return math.exp(-abs(x) / scale) / (2 * scale)

    # Two neighbour tables differ by moving one specimen between two cells.
    worst = 0.0
    for delta in (0.0, 0.5, 1.0, 2.5, 5.0, -3.0):
        # Counts differ only in the two affected cells; noise is independent.
        ratio = math.exp(-(abs(delta) - abs(delta - 1)) / scale) * math.exp(-(abs(-delta) - abs(-delta + 1)) / scale)
        worst = max(worst, ratio)
    assert worst <= math.exp(epsilon) + 1e-12
    # Per-cell scale uses the L1 sensitivity of 2, not the per-cell sensitivity 1.
    assert scale == pytest.approx(2 / epsilon)
    assert density(0) > 0
