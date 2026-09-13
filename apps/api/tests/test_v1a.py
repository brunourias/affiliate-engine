def test_settings_persist_and_validate(client):
    assert client.get('/api/v1/settings').json()['monthlyConfirmedCommissionGoalCents']==100000
    assert client.patch('/api/v1/settings',json={'monthlyConfirmedCommissionGoalCents':250000,'dailyPublicationLimit':7}).status_code==200
    result=client.get('/api/v1/settings').json(); assert result['monthlyConfirmedCommissionGoalCents']==250000; assert result['dailyPublicationLimit']==7
    assert client.patch('/api/v1/settings',json={'monthlyConfirmedCommissionGoalCents':-1}).status_code==422
    assert client.patch('/api/v1/settings',json={'timezone':'Invalid/Zone'}).status_code==422
def test_kill_switch_blocks_automatic_and_resume(client):
    assert client.post('/api/v1/automation/pause').json()['systemAutomationEnabled'] is False
    task=client.post('/api/v1/tasks',json={'type':'SYSTEM_HEARTBEAT','title':'auto','isAutomatic':True}).json()
    assert client.post(f"/api/v1/tasks/{task['id']}/run").status_code==409
    assert client.post('/api/v1/automation/resume').json()['systemAutomationEnabled'] is True
    assert client.post(f"/api/v1/tasks/{task['id']}/run").json()['status']=='COMPLETED'
def test_approval_reject_and_no_second_decision(client):
    from apps.api.app.db.session import SessionLocal
    from apps.api.app.db.models import Approval
    with SessionLocal() as db: item=Approval(type='STRATEGIC',title='Teste',description='Teste'); db.add(item); db.commit(); item_id=item.id
    assert client.post(f'/api/v1/approvals/{item_id}/reject',json={'reason':'não agora'}).json()['status']=='REJECTED'
    assert client.post(f'/api/v1/approvals/{item_id}/approve',json={}).status_code==409
def test_notifications_and_decision_log(client):
    client.post('/api/v1/automation/pause')
    notes=client.get('/api/v1/notifications').json(); assert notes and notes[0]['severity']=='CRITICAL'
    assert client.post(f"/api/v1/notifications/{notes[0]['id']}/read").json()['isRead'] is True
    logs=client.get('/api/v1/decisions').json(); assert any(x['action']=='AUTOMATION_PAUSED' for x in logs)
def test_task_transitions_and_controlled_failure(client):
    task=client.post('/api/v1/tasks',json={'type':'CONTROLLED_FAILURE','title':'falha','isAutomatic':False}).json()
    failed=client.post(f"/api/v1/tasks/{task['id']}/run").json(); assert failed['status']=='FAILED'; assert failed['error']
    assert client.post(f"/api/v1/tasks/{task['id']}/cancel").status_code==409
    pending=client.post('/api/v1/tasks',json={'type':'SYSTEM_HEARTBEAT','title':'cancelar','isAutomatic':False}).json()
    assert client.post(f"/api/v1/tasks/{pending['id']}/cancel").json()['status']=='CANCELED'
def test_health_and_dashboard(client):
    health=client.get('/api/v1/health'); assert health.status_code==200; assert health.json()['futureIntegrations']=='not_configured'
    dash=client.get('/api/v1/dashboard').json(); assert dash['commission']['sourceConnected'] is False
