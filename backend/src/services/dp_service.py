"""Differentially private grade-frequency publication.

Guarantees implemented here:
* one research-preset total epsilon per study, spent cumulatively and never reset;
* an atomic conditional UPDATE charges the budget, so concurrent requests cannot
  overdraw it;
* the noise seed and frozen input are persisted before any artifact is written,
  so an interrupted or failed release is resumed with the *same* noise and the
  charge is never refunded;
* the release identity is (study, frozen input digest, epsilon), so requesting
  the same statistic under another name reuses the charged publication, while a
  corrected grade or a new data version becomes a new identity and a new charge
  out of the remaining budget.
"""
import csv
import io
import json
import os
import secrets
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.config.settings import ARTIFACTS_DIR
from src.constants.enums import DpStatus
from src.models import DpBudget, DpPublication, DpReleaseName, GradeReading, Treatment
from src.services.dp_mechanism import (
    epsilon_to_micros,
    micros_to_epsilon,
    noisy_grade_table,
    release_digest,
    result_fingerprint,
)
from src.services.study_service import get_study


def charge_budget(db, budget_id, epsilon_micros):
    """Atomic conditional charge: concurrent requests can never overdraw."""
    charged = db.execute(
        update(DpBudget)
        .where(
            DpBudget.id == budget_id,
            DpBudget.spent_epsilon_micros + int(epsilon_micros) <= DpBudget.total_epsilon_micros,
        )
        .values(spent_epsilon_micros=DpBudget.spent_epsilon_micros + int(epsilon_micros))
    )
    return charged.rowcount == 1


def _artifact_path(publication_id):
    return Path(ARTIFACTS_DIR) / f'dp-publication-{publication_id}.json'


def _write_artifact(publication_id, payload):
    path = _artifact_path(publication_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.tmp-{secrets.token_hex(6)}')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True))
    os.replace(tmp, path)


def build_snapshot(db, study):
    """Freeze the internal analysis input.

    Retained server-side only (for deduplication and deterministic re-execution);
    never returned by the API nor written to a distributed artifact.
    """
    treatments = db.scalars(select(Treatment).where(Treatment.study_id == study.id).order_by(Treatment.code)).all()
    codes = {t.id: t.code for t in treatments}
    if not 2 <= len(treatments) <= 5:
        raise HTTPException(422, '全部预定义工艺须为2–5组，不能事后挑组')
    readings = db.scalars(select(GradeReading).where(GradeReading.study_id == study.id).order_by(GradeReading.specimen_code)).all()
    if len(readings) > 2000:
        raise HTTPException(422, '最多2000份独立试样')
    if len({r.specimen_code for r in readings}) != len(readings):
        raise HTTPException(422, '试样标识重复，不能当作独立试样')
    rows = []
    for r in readings:
        if r.treatment_id not in codes:
            raise HTTPException(422, '读数引用了研究之外的工艺')
        grade = r.grade
        if isinstance(grade, bool) or grade is None or float(grade) != int(grade) or not 1 <= grade <= 9:
            raise HTTPException(422, '形成等级必须为1–9整数，非等距性能量')
        rows.append({'specimen_code': r.specimen_code, 'treatment_code': codes[r.treatment_id], 'grade': int(grade)})
    counts = {t.code: sum(1 for r in rows if r['treatment_code'] == t.code) for t in treatments}
    if any(n < 5 for n in counts.values()):
        raise HTTPException(422, '每个预定义工艺至少5份独立试样；不得丢掉空组')
    return {
        'study': {'id': study.id, 'code': study.code, 'name': study.name},
        'treatments': [{'code': t.code, 'name': t.name} for t in treatments],
        'readings': sorted(rows, key=lambda r: (r['specimen_code'], r['treatment_code'], r['grade'])),
    }


# ---------------------------------------------------------------- budget ----

def get_budget(db, study_id):
    return db.scalar(select(DpBudget).where(DpBudget.study_id == study_id))


def budget_payload(budget):
    total = micros_to_epsilon(budget.total_epsilon_micros)
    spent = micros_to_epsilon(budget.spent_epsilon_micros)
    return {
        'study_id': budget.study_id,
        'total_epsilon': total,
        'spent_epsilon': spent,
        'remaining_epsilon': max(0.0, total - spent),
        'preset_by': budget.preset_by,
        'created_at': budget.created_at.isoformat(),
    }


def list_budgets(db):
    return [budget_payload(b) for b in db.scalars(select(DpBudget).order_by(DpBudget.study_id)).all()]


def set_budget(db, data, user):
    get_study(db, data.study_id)
    total = epsilon_to_micros(data.total_epsilon)
    budget = get_budget(db, data.study_id)
    if not budget:
        budget = DpBudget(study_id=data.study_id, total_epsilon_micros=total, spent_epsilon_micros=0, preset_by=user.email)
        db.add(budget)
    else:
        if total < budget.spent_epsilon_micros:
            raise HTTPException(409, '新总ε不能低于已花费ε；预算不重置')
        budget.total_epsilon_micros = total
        budget.preset_by = user.email
    db.commit()
    return budget_payload(budget)


# ----------------------------------------------------------- publications ----

def _names_for(db, publication_id):
    return [n.name for n in db.scalars(select(DpReleaseName).where(DpReleaseName.publication_id == publication_id).order_by(DpReleaseName.id)).all()]


def _release_payload(db, publication, reused=False):
    result = publication.result if publication.status == DpStatus.RELEASED else None
    return {
        'id': publication.id,
        'study_id': publication.study_id,
        'epsilon': micros_to_epsilon(publication.epsilon_micros),
        'status': publication.status,
        'release_digest': result.get('release_digest', '') if result else '',
        'names': _names_for(db, publication.id),
        'result': result,
        'error': publication.error,
        'reused': reused,
        'created_at': publication.created_at.isoformat(),
    }


def _find_publication(db, study_id, fingerprint, epsilon_micros):
    return db.scalar(select(DpPublication).where(
        DpPublication.study_id == study_id,
        DpPublication.fingerprint == fingerprint,
        DpPublication.epsilon_micros == epsilon_micros,
    ))


def _claim_name(db, publication, name, user):
    """Attach a new name to an existing charged publication (free reuse)."""
    existing = db.scalar(select(DpReleaseName).where(DpReleaseName.name == name))
    if existing:
        if existing.publication_id != publication.id:
            raise HTTPException(409, '发布名称已被另一份结果使用；同名不能指向不同内容')
        return
    db.add(DpReleaseName(publication_id=publication.id, name=name, requested_by=user.email))


def _execute(db, publication):
    """Deterministic from the persisted seed: a retry never redraws noise."""
    if publication.status == DpStatus.RELEASED:
        return publication
    try:
        result = noisy_grade_table(publication.snapshot, publication.epsilon_micros, int(publication.noise_seed, 16))
        result['publication_id'] = publication.id
        result['release_digest'] = release_digest(result)
        _write_artifact(publication.id, result)
        publication.result = result
        publication.error = ''
        publication.status = DpStatus.RELEASED
        db.commit()
    except Exception as exc:
        db.rollback()
        row = db.get(DpPublication, publication.id)
        if row and row.status != DpStatus.RELEASED:
            row.status = DpStatus.FAILED
            row.error = str(exc)[:600]
            db.commit()
        raise HTTPException(500, '发布计算中断；ε已扣、噪声种子已保留，重试将恢复同一发布且不重新抽噪')
    return publication


def create_release(db, data, user):
    study = get_study(db, data.study_id)
    epsilon_micros = epsilon_to_micros(data.epsilon)
    snapshot = build_snapshot(db, study)
    fingerprint = result_fingerprint(snapshot, epsilon_micros)

    existing = _find_publication(db, study.id, fingerprint, epsilon_micros)
    if existing:
        _claim_name(db, existing, data.name, user)
        db.commit()
        _execute(db, existing)
        return _release_payload(db, existing, reused=True)

    taken = db.scalar(select(DpReleaseName).where(DpReleaseName.name == data.name))
    if taken:
        raise HTTPException(409, '发布名称已被另一份结果使用；同名不能指向不同内容')

    budget = get_budget(db, study.id)
    if not budget:
        raise HTTPException(409, '研究尚未由复检负责人预设总ε，不能发布')
    if not charge_budget(db, budget.id, epsilon_micros):
        db.rollback()
        raise HTTPException(429, '剩余ε不足以发布本次结果；预算按研究累计且不重置')
    publication = DpPublication(
        study_id=study.id,
        fingerprint=fingerprint,
        epsilon_micros=epsilon_micros,
        status=DpStatus.RESERVED,
        noise_seed=secrets.token_hex(32),
        snapshot=snapshot,
    )
    db.add(publication)
    try:
        db.flush()
        db.add(DpReleaseName(publication_id=publication.id, name=data.name, requested_by=user.email))
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = _find_publication(db, study.id, fingerprint, epsilon_micros)
        if not winner:
            raise HTTPException(409, '并发发布冲突，请用未被占用的名称重试')
        _claim_name(db, winner, data.name, user)
        db.commit()
        _execute(db, winner)
        return _release_payload(db, winner, reused=True)
    _execute(db, publication)
    return _release_payload(db, publication)


def retry_release(db, publication_id):
    publication = get_publication(db, publication_id)
    _execute(db, publication)
    return _release_payload(db, publication)


def get_publication(db, publication_id):
    publication = db.get(DpPublication, publication_id)
    if not publication:
        raise HTTPException(404, '差分发布不存在')
    return publication


def get_release(db, publication_id):
    return _release_payload(db, get_publication(db, publication_id))


def list_releases(db, study_id=None):
    stmt = select(DpPublication).order_by(DpPublication.id.desc())
    if study_id is not None:
        stmt = stmt.where(DpPublication.study_id == study_id)
    return [_release_payload(db, p) for p in db.scalars(stmt).all()]


def list_release_names(db):
    return [{'id': n.id, 'publication_id': n.publication_id, 'name': n.name, 'requested_by': n.requested_by, 'created_at': n.created_at.isoformat()}
            for n in db.scalars(select(DpReleaseName).order_by(DpReleaseName.id)).all()]


def export_release(db, publication_id):
    publication = get_publication(db, publication_id)
    if publication.status != DpStatus.RELEASED:
        raise HTTPException(409, '仅已完成的差分发布可分发；失败或保留中的发布不导出')
    result = publication.result
    budget = get_budget(db, publication.study_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['publication_id', 'study_code', 'status', 'mechanism', 'epsilon', 'noise_scale', 'sensitivity_l1', 'adjacency', 'release_digest', 'names'])
    writer.writerow([
        publication.id,
        publication.snapshot['study']['code'],
        publication.status,
        result['mechanism'],
        result['epsilon'],
        result['noise_scale'],
        result['sensitivity_l1'],
        result['adjacency'],
        result['release_digest'],
        ' / '.join(_names_for(db, publication.id)),
    ])
    writer.writerow(['budget_total_epsilon', micros_to_epsilon(budget.total_epsilon_micros) if budget else ''])
    writer.writerow(['budget_spent_epsilon', micros_to_epsilon(budget.spent_epsilon_micros) if budget else ''])
    writer.writerow([])
    writer.writerow(['treatment_code', 'treatment_name', 'grade', 'noisy_count'])
    for treatment in result['treatments']:
        for cell in treatment['noisy_counts']:
            writer.writerow([treatment['code'], treatment['name'], cell['grade'], cell['noisy_count']])
    writer.writerow([])
    writer.writerow(['disclosure', result['disclosure']])
    writer.writerow(['boundary', '加噪频数为负或非整数属正常；不是真实试样数、比例、精确检验或工艺优劣。'])
    return '﻿' + out.getvalue()
