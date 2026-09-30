from apps.api.app.db.session import SessionLocal
import pytest
from sqlalchemy import func, select
from apps.api.app.db.models import Approval, Campaign, CampaignAngle, CampaignChannel, CampaignExperiment, Creative, CuratorAssessment, CuratorCandidate, DecisionLog, MediaAsset, MediaJob, PublicationExecution

def seed(status="APPROVED", trust="PASS"):
    with SessionLocal() as db:
        c=CuratorCandidate(provider="OTHER",source_type="MANUAL",entity_type="MANUAL",working_title="Produto aprovado",opportunity_review_status="COMMERCIAL_REVIEW",commercial_analysis_status="ASSESSMENT_AVAILABLE",campaign_handoff_status=status)
        db.add(c); db.flush()
        a=CuratorAssessment(candidate_id=c.id,assessment_version=1,evidence_status="SUFFICIENT",evidence_level="PUBLIC_VERIFIED",trust_gate=trust,trust_reasons=[],trust_warnings=[],recommendation_score=None, recommendation_coverage_percent=0,recommendation_label=None,opportunity_score=None,opportunity_coverage_percent=0,price_verdict="UNKNOWN",editorial_verdict="INSUFFICIENT_EVIDENCE" if trust=="INSUFFICIENT_EVIDENCE" else "WORTH_IT",recommendation_pillars={},opportunity_pillars={},evidence_ids_used=[],unknown_fields=[],rationale={})
        db.add(a); db.flush(); c.campaign_handoff_assessment_id=a.id; db.commit(); return c.id,a.id

def test_handoff_creates_draft_once_and_logs_once(client):
    cid,aid=seed()
    first=client.post(f"/api/v1/campaigns/from-handoff/{cid}",json={"name":"Minha campanha"})
    assert first.status_code==200; body=first.json(); assert body["created"] is True
    campaign=body["campaign"]; assert campaign["status"]=="DRAFT" and campaign["assessmentId"]==aid and campaign["affiliateUrl"] is None
    replay=client.post(f"/api/v1/campaigns/from-handoff/{cid}",json={"name":"Outro nome"}).json()
    assert replay["created"] is False and replay["campaign"]["id"]==campaign["id"] and replay["campaign"]["name"]=="Minha campanha"
    with SessionLocal() as db:
        assert db.scalar(__import__('sqlalchemy').select(__import__('sqlalchemy').func.count()).select_from(DecisionLog).where(DecisionLog.action=="CAMPAIGN_CREATED"))==1
        saved=db.get(Campaign,campaign["id"])
        assert saved.creation_source=="CAMPAIGN_HANDOFF" and saved.creation_key==f"CAMPAIGN_HANDOFF:{aid}"
        assert db.scalar(select(func.count()).select_from(CampaignChannel).where(CampaignChannel.campaign_id==saved.id))==0
        assert db.scalar(select(func.count()).select_from(CampaignAngle).where(CampaignAngle.campaign_id==saved.id))==0
        assert db.scalar(select(func.count()).select_from(CampaignExperiment).where(CampaignExperiment.campaign_id==saved.id))==0
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_id==saved.id))==0

def test_reject_stale_and_legacy_duplicate_are_safe(client):
    cid,aid=seed("REJECTED")
    assert client.post(f"/api/v1/campaigns/from-handoff/{cid}",json={}).status_code==409
    cid,aid=seed()
    with SessionLocal() as db:
        a=db.get(CuratorAssessment,aid); c=db.get(CuratorCandidate,cid)
        for name in ("legado A","legado B"):
            db.add(Campaign(candidate_id=cid,assessment_id=aid,name=name,status="DRAFT",objective="DISCOVERY",editorial_verdict_snapshot=a.editorial_verdict,trust_gate_snapshot=a.trust_gate,recommendation_score_snapshot=None,opportunity_score_snapshot=None,price_verdict_snapshot=a.price_verdict,campaign_priority="UNKNOWN",disclosure_text="x",trust_warnings_snapshot=[],required_disclosures=[],required_warnings=[],forbidden_claims=[]))
        db.commit()
    assert client.post(f"/api/v1/campaigns/from-handoff/{cid}",json={}).status_code==409

def test_insufficient_evidence_creates_not_ready_draft(client):
    cid,_=seed(trust="INSUFFICIENT_EVIDENCE")
    campaign=client.post(f"/api/v1/campaigns/from-handoff/{cid}",json={}).json()["campaign"]
    assert client.get(f"/api/v1/campaigns/{campaign['id']}/readiness").json()["state"]=="NOT_READY"

@pytest.mark.parametrize("status",["NOT_DECIDED","REJECTED","STALE"])
def test_non_approved_handoff_is_blocked(client,status):
    cid,_=seed(status)
    assert client.post(f"/api/v1/campaigns/from-handoff/{cid}",json={}).status_code==409

def test_archived_wrong_workflow_and_missing_analysis_are_blocked(client):
    cid,_=seed()
    with SessionLocal() as db:
        c=db.get(CuratorCandidate,cid); c.status="ARCHIVED"; db.commit()
    assert client.post(f"/api/v1/campaigns/from-handoff/{cid}",json={}).json()["detail"]=="CANDIDATE_ARCHIVED"
    cid,_=seed()
    with SessionLocal() as db:
        c=db.get(CuratorCandidate,cid); c.opportunity_review_status="PENDING"; db.commit()
    assert client.post(f"/api/v1/campaigns/from-handoff/{cid}",json={}).status_code==409
    cid,_=seed()
    with SessionLocal() as db:
        c=db.get(CuratorCandidate,cid); c.commercial_analysis_status="WAITING_FOR_OFFER"; db.commit()
    assert client.post(f"/api/v1/campaigns/from-handoff/{cid}",json={}).status_code==409

def test_legacy_endpoints_require_handoff_and_ignore_objective(client):
    cid,aid=seed("NOT_DECIDED")
    assert client.post("/api/v1/campaigns",json={"assessmentId":aid,"name":"x","objective":"CONVERSION"}).status_code==409
    assert client.post(f"/api/v1/campaigns/from-assessment/{aid}",json={"name":"x"}).status_code==409
    cid,aid=seed()
    response=client.post("/api/v1/campaigns",json={"assessmentId":aid,"name":"x","objective":"PRICE_ALERT"})
    assert response.status_code==201 and response.json()["objective"]=="EDUCATION"
