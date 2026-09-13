import asyncio

from apps.api.app.db.models import AgentTask, Approval
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.scheduler import Scheduler


def test_settings_persist_and_validate(client):
    assert client.get('/api/v1/settings').json()['monthlyConfirmedCommissionGoalCents'] == 100000
    response = client.patch('/api/v1/settings', json={'monthlyConfirmedCommissionGoalCents': 250000, 'dailyPublicationLimit': 7})
    assert response.status_code == 200
    result = client.get('/api/v1/settings').json()
    assert result['monthlyConfirmedCommissionGoalCents'] == 250000
    assert result['dailyPublicationLimit'] == 7
    assert client.patch('/api/v1/settings', json={'monthlyConfirmedCommissionGoalCents': -1}).status_code == 422
    assert client.patch('/api/v1/settings', json={'timezone': 'Invalid/Zone'}).status_code == 422


def test_kill_switch_blocks_automatic_and_resume(client):
    assert client.post('/api/v1/automation/pause').json()['systemAutomationEnabled'] is False
    task = client.post('/api/v1/tasks', json={'type': 'SYSTEM_HEARTBEAT', 'title': 'auto', 'isAutomatic': True}).json()
    assert client.post(f"/api/v1/tasks/{task['id']}/run").status_code == 409
    assert client.post('/api/v1/automation/resume').json()['systemAutomationEnabled'] is True
    assert client.post(f"/api/v1/tasks/{task['id']}/run").json()['status'] == 'COMPLETED'


def test_scheduler_tick_respects_kill_switch_and_processes_after_resume(client):
    client.post('/api/v1/automation/pause')
    task_id = client.post('/api/v1/tasks', json={'type': 'SYSTEM_HEARTBEAT', 'title': 'fila automática', 'isAutomatic': True}).json()['id']
    local_scheduler = Scheduler()
    local_scheduler.tick()
    with SessionLocal() as db:
        assert db.get(AgentTask, task_id).status == 'PENDING'
    client.post('/api/v1/automation/resume')
    local_scheduler.tick()
    with SessionLocal() as db:
        assert db.get(AgentTask, task_id).status == 'COMPLETED'


def test_scheduler_start_is_idempotent_and_stop_is_clean():
    async def scenario():
        local_scheduler = Scheduler()
        first = local_scheduler.start()
        second = local_scheduler.start()
        assert first is second
        await asyncio.sleep(0)
        await local_scheduler.stop()
        assert local_scheduler._task is None
        assert first.done()
    asyncio.run(scenario())


def test_approval_and_rejection_are_final(client):
    with SessionLocal() as db:
        approved = Approval(type='STRATEGIC', title='Aprovar', description='Teste')
        rejected = Approval(type='FINANCIAL', title='Rejeitar', description='Teste')
        db.add_all([approved, rejected]); db.commit()
        approved_id, rejected_id = approved.id, rejected.id
    assert client.post(f'/api/v1/approvals/{approved_id}/approve', json={'reason': 'ok'}).json()['status'] == 'APPROVED'
    assert client.post(f'/api/v1/approvals/{rejected_id}/reject', json={'reason': 'não agora'}).json()['status'] == 'REJECTED'
    assert client.post(f'/api/v1/approvals/{approved_id}/reject', json={}).status_code == 409
    assert client.post(f'/api/v1/approvals/{rejected_id}/approve', json={}).status_code == 409


def test_notifications_and_decision_log(client):
    client.post('/api/v1/automation/pause')
    notes = client.get('/api/v1/notifications').json()
    assert notes and notes[0]['severity'] == 'CRITICAL'
    assert client.post(f"/api/v1/notifications/{notes[0]['id']}/read").json()['isRead'] is True
    assert any(item['action'] == 'AUTOMATION_PAUSED' for item in client.get('/api/v1/decisions').json())


def test_task_transitions_and_controlled_failure(client):
    task = client.post('/api/v1/tasks', json={'type': 'CONTROLLED_FAILURE', 'title': 'falha', 'isAutomatic': False}).json()
    failed = client.post(f"/api/v1/tasks/{task['id']}/run").json()
    assert failed['status'] == 'FAILED' and failed['error']
    assert client.post(f"/api/v1/tasks/{task['id']}/cancel").status_code == 409
    pending = client.post('/api/v1/tasks', json={'type': 'SYSTEM_HEARTBEAT', 'title': 'cancelar', 'isAutomatic': False}).json()
    assert client.post(f"/api/v1/tasks/{pending['id']}/cancel").json()['status'] == 'CANCELED'


def test_manual_task_remains_allowed_with_kill_switch(client):
    client.post('/api/v1/automation/pause')
    task = client.post('/api/v1/tasks', json={'type': 'SYSTEM_HEARTBEAT', 'title': 'manual', 'isAutomatic': False}).json()
    assert client.post(f"/api/v1/tasks/{task['id']}/run").json()['status'] == 'COMPLETED'


def test_health_and_dashboard_do_not_invent_financial_data(client):
    health = client.get('/api/v1/health')
    assert health.status_code == 200
    assert health.json()['futureIntegrations'] == 'not_configured'
    dashboard = client.get('/api/v1/dashboard').json()
    assert dashboard['commission']['sourceConnected'] is False
    assert dashboard['commission']['confirmedCents'] == 0
