from apps.api.app.db.session import SessionLocal
from apps.api.app.db.models import CuratorCandidate,CuratorAssessment

def assessment(verdict="BUY_NOW",trust="PASS",opportunity=82,evidence_level="PUBLIC_VERIFIED"):
    with SessionLocal() as db:
        c=CuratorCandidate(provider="OTHER",source_type="MANUAL",entity_type="MANUAL",working_title="Produto teste")
        db.add(c);db.flush();a=CuratorAssessment(candidate_id=c.id,assessment_version=1,evidence_status="SUFFICIENT",evidence_level=evidence_level,trust_gate=trust,trust_reasons=[],trust_warnings=[{"code":"LIMIT","message":"Uso doméstico"}] if trust=="WARN" else [],recommendation_score=80,recommendation_coverage_percent=100,recommendation_label="STRONG",opportunity_score=opportunity,opportunity_coverage_percent=100,price_verdict="GOOD_PRICE" if verdict!="WAIT_FOR_BETTER_PRICE" else "EXPENSIVE",editorial_verdict=verdict,recommendation_pillars={},opportunity_pillars={},evidence_ids_used=[],unknown_fields=[],rationale={})
        db.add(a);db.commit();return a.id,c.id
def create(client,**kwargs):
    aid,_=assessment(**kwargs);r=client.post("/api/v1/campaigns",json={"assessmentId":aid,"name":"Campanha teste"});return r,aid
def ready(client,cid):
    client.patch(f"/api/v1/campaigns/{cid}",json={"targetAudience":"Público","ctaStrategy":"Saiba mais","affiliateUrl":"https://example.com/a?x=1"})
    client.post(f"/api/v1/campaigns/{cid}/channels",json={"channel":"TIKTOK"})
    angle=client.post(f"/api/v1/campaigns/{cid}/angles",json={"angleType":"SMART_BUYING","title":"Vale a pena?","premise":"Compra consciente"}).json()
    client.post(f"/api/v1/campaigns/{cid}/experiments",json={"angleId":angle["id"],"hypothesis":"Hook melhora retenção","targetChannel":"TIKTOK"})
def test_supported_verdicts_and_suggestions(client):
    for verdict,want in [("BUY_NOW","CONVERSION"),("WORTH_IT","EDUCATION"),("WAIT_FOR_BETTER_PRICE","PRICE_ALERT")]:
        r,_=create(client,verdict=verdict);assert r.status_code==201;assert r.json()["objective"]==want
def test_worth_it_with_unknown_opportunity_persists_snapshot(client):
    r,assessment_id=create(client,verdict="WORTH_IT",trust="PASS",opportunity=None)
    assert r.status_code==201
    body=r.json();assert body["id"] and body["assessmentId"]==assessment_id and body["opportunityScoreSnapshot"] is None
    persisted=client.get("/api/v1/campaigns").json();assert len(persisted)==1 and persisted[0]["id"]==body["id"] and persisted[0]["candidateId"]==body["candidateId"]
def test_blocked_assessments(client):
    for args in [dict(trust="BLOCK"),dict(verdict="NOT_RECOMMENDED"),dict(trust="INSUFFICIENT_EVIDENCE",verdict="INSUFFICIENT_EVIDENCE")]:assert create(client,**args)[0].status_code==409
    assert client.post("/api/v1/campaigns",json={"name":"sem assessment"}).status_code==422
def test_snapshot_priority_warnings_and_claims(client):
    r,aid=create(client,trust="WARN");body=r.json();assert body["assessmentId"]==aid and body["campaignPriority"]=="VERY_HIGH";assert body["trustWarningsSnapshot"];assert "OWN_TEST_CLAIM" in body["forbiddenClaims"]
    r,_=create(client,opportunity=None);assert r.json()["campaignPriority"]=="UNKNOWN"
def test_snapshot_does_not_change(client):
    r,aid=create(client);cid=r.json()["id"]
    with SessionLocal() as db:
        old=db.get(CuratorAssessment,aid);new=CuratorAssessment(**{c.name:getattr(old,c.name) for c in CuratorAssessment.__table__.columns if c.name not in {"id","created_at"}});new.assessment_version=2;new.opportunity_score=1;new.previous_assessment_id=old.id;db.add(new);db.commit()
    assert client.get(f"/api/v1/campaigns/{cid}").json()["opportunityScoreSnapshot"]==82
def test_readiness_children_and_approval_sync(client):
    r,_=create(client);cid=r.json()["id"];assert client.get(f"/api/v1/campaigns/{cid}/readiness").json()["state"]=="NOT_READY";ready(client,cid);assert client.get(f"/api/v1/campaigns/{cid}/readiness").json()["state"]=="READY_FOR_APPROVAL"
    approval=client.post(f"/api/v1/campaigns/{cid}/submit-for-approval").json();assert approval["type"]=="CAMPAIGN";assert client.get(f"/api/v1/campaigns/{cid}").json()["status"]=="PENDING_APPROVAL";client.post(f'/api/v1/approvals/{approval["id"]}/approve',json={});assert client.get(f"/api/v1/campaigns/{cid}").json()["status"]=="APPROVED"
def test_reject_and_no_silent_approval(client):
    r,_=create(client);cid=r.json()["id"];ready(client,cid);approval=client.post(f"/api/v1/campaigns/{cid}/submit-for-approval").json();client.post(f'/api/v1/approvals/{approval["id"]}/reject',json={"reason":"ajustar"});assert client.get(f"/api/v1/campaigns/{cid}").json()["status"]=="REJECTED"
def test_manual_url_validation_and_conversion_requires_link(client):
    r,_=create(client);cid=r.json()["id"];assert client.patch(f"/api/v1/campaigns/{cid}",json={"affiliateUrl":"javascript:alert(1)"}).status_code==422;client.patch(f"/api/v1/campaigns/{cid}",json={"targetAudience":"X","ctaStrategy":"X"});client.post(f"/api/v1/campaigns/{cid}/channels",json={"channel":"INSTAGRAM_REELS"});client.post(f"/api/v1/campaigns/{cid}/angles",json={"angleType":"REVIEW","title":"R","premise":"P"});client.post(f"/api/v1/campaigns/{cid}/experiments",json={"hypothesis":"H"});assert not client.get(f"/api/v1/campaigns/{cid}/readiness").json()["checks"]["affiliateLink"]
def test_max_twelve_experiments_and_pause_archive(client):
    r,_=create(client);cid=r.json()["id"]
    for i in range(12):assert client.post(f"/api/v1/campaigns/{cid}/experiments",json={"hypothesis":str(i)}).status_code==201
    assert client.post(f"/api/v1/campaigns/{cid}/experiments",json={"hypothesis":"13"}).status_code==409;assert client.post(f"/api/v1/campaigns/{cid}/pause").status_code==409;assert client.post(f"/api/v1/campaigns/{cid}/archive").json()["status"]=="ARCHIVED"

def test_pending_approval_locks_all_campaign_content(client):
    r,_=create(client);cid=r.json()["id"];ready(client,cid);approval=client.post(f"/api/v1/campaigns/{cid}/submit-for-approval").json()
    assert client.patch(f"/api/v1/campaigns/{cid}",json={"ctaStrategy":"alterado"}).status_code==409
    assert client.post(f"/api/v1/campaigns/{cid}/channels",json={"channel":"YOUTUBE_SHORTS"}).status_code==409
    assert client.post(f"/api/v1/campaigns/{cid}/angles",json={"angleType":"REVIEW","title":"Novo","premise":"Novo"}).status_code==409
    assert client.post(f"/api/v1/campaigns/{cid}/experiments",json={"hypothesis":"Nova"}).status_code==409
    assert client.get(f"/api/v1/approvals/{approval['id']}").json()["entityId"]==cid

def test_approved_paused_and_archived_are_locked(client):
    r,_=create(client);cid=r.json()["id"];ready(client,cid);approval=client.post(f"/api/v1/campaigns/{cid}/submit-for-approval").json();client.post(f"/api/v1/approvals/{approval['id']}/approve",json={})
    assert client.patch(f"/api/v1/campaigns/{cid}",json={"name":"x"}).status_code==409
    assert client.post(f"/api/v1/campaigns/{cid}/pause").status_code==200
    assert client.patch(f"/api/v1/campaigns/{cid}",json={"name":"x"}).status_code==409
    assert client.post(f"/api/v1/campaigns/{cid}/archive").status_code==200
    assert client.patch(f"/api/v1/campaigns/{cid}",json={"name":"x"}).status_code==409
