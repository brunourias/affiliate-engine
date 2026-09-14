from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from apps.api.app.db.models import CuratorCandidate,CuratorEvidence,RadarRun,RadarSignal
from apps.api.app.db.session import SessionLocal
def manual(client):return client.post('/api/v1/curator/candidates',json={'provider':'MERCADO_LIVRE','entityType':'ITEM','sourceUrl':'https://produto.mercadolivre.com.br/MLB-123'}).json()
def test_manual_candidate_parses_id_without_network(client):
    c=manual(client);assert c['externalId']=='MLB123' and c['evidenceStatus']=='INSUFFICIENT_EVIDENCE';assert 'score' not in str(c).lower()
def test_radar_intake_is_idempotent_and_preserves_provenance(client):
    with SessionLocal() as db:
        run=RadarRun(provider='MERCADO_LIVRE',site_id='MLB');db.add(run);db.flush();s=RadarSignal(radar_run_id=run.id,provider='MERCADO_LIVRE',site_id='MLB',source_type='HIGHLIGHT_CATEGORY',source_capability='HIGHLIGHTS_CATEGORY',entity_type='ITEM',external_id='MLB9',rank=2);db.add(s);db.commit();sid=s.id;rid=run.id
    a=client.post('/api/v1/curator/candidates/from-radar/'+sid).json();b=client.post('/api/v1/curator/candidates/from-radar/'+sid).json();assert a['id']==b['id'] and a['sourceRadarRunId']==rid
    ev=client.get('/api/v1/curator/candidates/'+a['id']+'/evidence').json();assert len(ev)==1 and ev[0]['evidenceType']=='MARKET_SIGNAL' and ev[0]['valueJson']['rank']==2
def test_query_without_id_deduplicates_by_normalized_text_and_category(client):
    with SessionLocal() as db:
        r=RadarRun(provider='MERCADO_LIVRE',site_id='MLB');db.add(r);db.flush();ids=[]
        for text in ['  Furadeira  sem fio ','furadeira sem fio']:
            s=RadarSignal(radar_run_id=r.id,provider='MERCADO_LIVRE',site_id='MLB',source_type='TREND_CATEGORY',source_capability='TRENDS_CATEGORY',entity_type='QUERY',display_text=text,category_external_id='MLB1');db.add(s);db.flush();ids.append(s.id)
        db.commit()
    assert client.post('/api/v1/curator/candidates/from-radar/'+ids[0]).json()['id']==client.post('/api/v1/curator/candidates/from-radar/'+ids[1]).json()['id']
def test_evidence_price_stale_levels_and_status(client):
    c=manual(client);cid=c['id'];past=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    price=client.post(f'/api/v1/curator/candidates/{cid}/evidence',json={'evidenceType':'CURRENT_PRICE','valueCents':12990,'sourceKind':'MANUAL_OPERATOR','validUntil':past}).json();assert price['valueCents']==12990 and price['isStale']
    for typ,source,verified in [('CURRENT_PRICE','MANUAL_OPERATOR','VERIFIED'),('COMMUNITY_SIGNAL','COMMUNITY','VERIFIED'),('LIMITATION','MANUAL_OPERATOR','VERIFIED'),('USE_CASE','MANUAL_OPERATOR','VERIFIED')]:client.post(f'/api/v1/curator/candidates/{cid}/evidence',json={'evidenceType':typ,'valueText':'evidência','valueCents':100 if typ=='CURRENT_PRICE' else None,'sourceKind':source,'verificationStatus':verified})
    check=client.get(f'/api/v1/curator/candidates/{cid}/checklist').json();assert check['evidenceStatus']=='VERIFIED' and check['evidenceLevel']=='COMMUNITY_VALIDATED';assert any(x['status']=='STALE' for x in check['items']) is False
    client.post(f'/api/v1/curator/candidates/{cid}/evidence',json={'evidenceType':'OWN_TEST','valueText':'testado','sourceKind':'OWN_TEST','verificationStatus':'UNVERIFIED'});assert client.get(f'/api/v1/curator/candidates/{cid}/checklist').json()['evidenceLevel']!='OWNED_AND_TESTED'
    client.post(f'/api/v1/curator/candidates/{cid}/evidence',json={'evidenceType':'OWN_TEST','valueText':'testado','sourceKind':'OWN_TEST','verificationStatus':'VERIFIED'});assert client.get(f'/api/v1/curator/candidates/{cid}/checklist').json()['evidenceLevel']=='OWNED_AND_TESTED'
def test_transitions_archive_reopen_and_history(client):
    cid=manual(client)['id'];assert client.patch(f'/api/v1/curator/candidates/{cid}',json={'status':'INVESTIGATING'}).status_code==200;assert client.patch(f'/api/v1/curator/candidates/{cid}',json={'status':'READY_FOR_REVIEW'}).status_code==200;assert client.post(f'/api/v1/curator/candidates/{cid}/archive').json()['status']=='ARCHIVED';assert client.post(f'/api/v1/curator/candidates/{cid}/reopen').json()['status']=='INVESTIGATING'
