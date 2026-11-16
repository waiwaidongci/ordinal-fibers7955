import pytest
from sqlalchemy import select

from src.models import GradeReading, GradeStudy, User
from src.utils.security import issue_token


def _auth(db, role):
    user = db.scalar(select(User).where(User.email == f'{role}@qingnie.local'))
    return {'Authorization': 'Bearer ' + issue_token(user)}


def _study(db):
    return db.scalar(select(GradeStudy.id).where(GradeStudy.code == 'QN-SHIFT'))


def test_budget_requires_admin(client, seeded):
    sid = _study(seeded)
    body = {'study_id': sid, 'total_epsilon': 1.0}
    assert client.post('/dp/budgets', json=body, headers=_auth(seeded, 'analyst')).status_code == 403
    assert client.post('/dp/budgets', json=body, headers=_auth(seeded, 'viewer')).status_code == 403
    created = client.post('/dp/budgets', json=body, headers=_auth(seeded, 'admin'))
    assert created.status_code == 200, created.text
    assert created.json()['remaining_epsilon'] == pytest.approx(1.0)
    assert created.json()['spent_epsilon'] == 0.0


def test_release_flow_and_read_only_viewer(client, seeded):
    sid = _study(seeded)
    admin = _auth(seeded, 'admin')
    analyst = _auth(seeded, 'analyst')
    viewer = _auth(seeded, 'viewer')
    assert client.post('/dp/budgets', json={'study_id': sid, 'total_epsilon': 0.5}, headers=admin).status_code == 200

    payload = {'study_id': sid, 'name': '对外合作 · 发布甲', 'epsilon': 0.2}
    assert client.post('/dp/releases', json=payload, headers=viewer).status_code == 403
    first = client.post('/dp/releases', json=payload, headers=analyst)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body['status'] == 'released' and body['reused'] is False
    assert body['result']['sensitivity_l1'] == 2
    assert 'snapshot' not in body

    reused = client.post('/dp/releases', json={**payload, 'name': '对外合作 · 改名'}, headers=analyst)
    assert reused.status_code == 201
    assert reused.json()['id'] == body['id'] and reused.json()['reused'] is True

    budget = client.get('/dp/budgets', headers=viewer).json()[0]
    assert budget['spent_epsilon'] == pytest.approx(0.2)

    detail = client.get(f"/dp/releases/{body['id']}", headers=viewer)
    assert detail.status_code == 200
    assert detail.json()['result'] == body['result']

    exported = client.get(f"/dp/releases/{body['id']}/export", headers=viewer)
    assert exported.status_code == 200
    assert 'noisy_count' in exported.text
    specimen = seeded.scalar(select(GradeReading.specimen_code).where(GradeReading.study_id == sid))
    assert specimen not in exported.text


def test_release_over_budget_is_rejected_without_new_row(client, seeded):
    sid = _study(seeded)
    headers = _auth(seeded, 'analyst')
    client.post('/dp/budgets', json={'study_id': sid, 'total_epsilon': 0.1}, headers=_auth(seeded, 'admin'))
    assert client.post('/dp/releases', json={'study_id': sid, 'name': '第一笔', 'epsilon': 0.1}, headers=headers).status_code == 201
    # A corrected grade changes the identity and would need another charge.
    reading = seeded.scalar(select(GradeReading).where(GradeReading.study_id == sid).order_by(GradeReading.specimen_code))
    reading.grade = reading.grade + 1 if reading.grade < 9 else reading.grade - 1
    seeded.commit()
    denied = client.post('/dp/releases', json={'study_id': sid, 'name': '更正版本', 'epsilon': 0.1}, headers=headers)
    assert denied.status_code == 429
    assert client.get('/dp/budgets', headers=headers).json()[0]['spent_epsilon'] == pytest.approx(0.1)
    assert client.get('/dp/releases', headers=headers).json()[0]['names'] == ['第一笔']


def test_epsilon_validation(client, seeded):
    sid = _study(seeded)
    admin = _auth(seeded, 'admin')
    for bad in (0, -1, 1e-9, 1001):
        response = client.post('/dp/budgets', json={'study_id': sid, 'total_epsilon': bad}, headers=admin)
        assert response.status_code == 422, (bad, response.text)
    assert client.post('/dp/budgets', json={'study_id': sid, 'total_epsilon': 0.1234567}, headers=admin).status_code == 422
