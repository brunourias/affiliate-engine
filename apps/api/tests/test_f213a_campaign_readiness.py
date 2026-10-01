from sqlalchemy import func, select

from apps.api.app.db.models import Approval, Campaign, CampaignAngle, CampaignChannel, CampaignExperiment, CuratorAssessment, DecisionLog
from apps.api.app.db.session import SessionLocal
from apps.api.tests.test_v1d_campaigns import create, ready


def campaign(client, **kwargs):
    response, assessment_id = create(client, **kwargs)
    assert response.status_code == 201
    return response.json()["id"], assessment_id


def test_complete_campaign_is_ready_with_stable_explicit_contract(client):
    campaign_id, _ = campaign(client)
    ready(client, campaign_id)
    result = client.get(f"/api/v1/campaigns/{campaign_id}/readiness").json()
    assert result["state"] == "READY_FOR_APPROVAL"
    assert result["campaignStatus"] == "DRAFT"
    assert result["nextAction"] == "READY_TO_SUBMIT"
    assert result["blockers"] == []
    assert result["checks"]["sourceAssessmentCurrent"]
    assert result["checks"]["editorialPositioning"] and result["checks"]["primaryMessage"]
    assert result["channelCount"] == result["angleCount"] == result["experimentCount"] == 1


def test_readiness_is_read_only(client):
    campaign_id, _ = campaign(client)
    with SessionLocal() as db:
        row = db.get(Campaign, campaign_id)
        before = (row.updated_at, db.scalar(select(func.count()).select_from(DecisionLog)), db.scalar(select(func.count()).select_from(Approval)))
    client.get(f"/api/v1/campaigns/{campaign_id}/readiness")
    with SessionLocal() as db:
        row = db.get(Campaign, campaign_id)
        after = (row.updated_at, db.scalar(select(func.count()).select_from(DecisionLog)), db.scalar(select(func.count()).select_from(Approval)))
    assert after == before


def test_latest_assessment_makes_campaign_outdated(client):
    campaign_id, assessment_id = campaign(client)
    ready(client, campaign_id)
    with SessionLocal() as db:
        old = db.get(CuratorAssessment, assessment_id)
        values = {column.name: getattr(old, column.name) for column in CuratorAssessment.__table__.columns if column.name not in {"id", "created_at"}}
        values.update(assessment_version=2, previous_assessment_id=old.id)
        db.add(CuratorAssessment(**values)); db.commit()
    result = client.get(f"/api/v1/campaigns/{campaign_id}/readiness").json()
    assert result["state"] == "NOT_READY" and not result["checks"]["sourceAssessmentCurrent"]
    assert result["blockers"][0]["code"] == "ASSESSMENT_OUTDATED"
    assert result["nextAction"] == "REVIEW_UPDATED_ASSESSMENT"
    response = client.post(f"/api/v1/campaigns/{campaign_id}/submit-for-approval")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "CAMPAIGN_NOT_READY"


def test_trust_and_editorial_assessment_snapshots_remain_authoritative(client):
    for kwargs, code in [({"trust": "INSUFFICIENT_EVIDENCE", "verdict": "INSUFFICIENT_EVIDENCE"}, "INSUFFICIENT_EVIDENCE"), ({"trust": "BLOCK"}, "TRUST_GATE_BLOCKED"), ({"verdict": "NOT_RECOMMENDED"}, "EDITORIAL_VERDICT_NOT_ELIGIBLE")]:
        campaign_id, _ = campaign(client, **kwargs); ready(client, campaign_id)
        result = client.get(f"/api/v1/campaigns/{campaign_id}/readiness").json()
        assert result["state"] == "NOT_READY" and code in {item["code"] for item in result["blockers"]}


def test_strategy_and_structure_requirements_have_stable_blockers(client):
    campaign_id, _ = campaign(client)
    result = client.get(f"/api/v1/campaigns/{campaign_id}/readiness").json()
    assert [item["code"] for item in result["blockers"]] == ["TARGET_AUDIENCE_REQUIRED", "EDITORIAL_POSITIONING_REQUIRED", "PRIMARY_MESSAGE_REQUIRED", "CTA_REQUIRED", "AFFILIATE_LINK_REQUIRED", "CHANNEL_REQUIRED", "ANGLE_REQUIRED", "EXPERIMENT_REQUIRED"]
    assert result["nextAction"] == "COMPLETE_STRATEGY"
    assert client.patch(f"/api/v1/campaigns/{campaign_id}", json={"targetAudience": "   ", "editorialPositioning": " ", "primaryMessage": "  ", "ctaStrategy": " "}).status_code == 200
    result = client.get(f"/api/v1/campaigns/{campaign_id}/readiness").json()
    assert {item["code"] for item in result["blockers"]} >= {"TARGET_AUDIENCE_REQUIRED", "EDITORIAL_POSITIONING_REQUIRED", "PRIMARY_MESSAGE_REQUIRED", "CTA_REQUIRED"}


def test_missing_disclosure_channel_angle_and_experiment_block(client):
    campaign_id, _ = campaign(client)
    with SessionLocal() as db:
        row = db.get(Campaign, campaign_id); row.disclosure_text = "   "; db.commit()
    client.post(f"/api/v1/campaigns/{campaign_id}/channels", json={"channel": "TIKTOK", "enabled": False})
    client.post(f"/api/v1/campaigns/{campaign_id}/angles", json={"angleType": "REVIEW", "title": "Inativo", "premise": "P", "status": "DISABLED"})
    client.post(f"/api/v1/campaigns/{campaign_id}/experiments", json={"hypothesis": "Cancelado", "status": "CANCELLED"})
    client.post(f"/api/v1/campaigns/{campaign_id}/experiments", json={"hypothesis": "Estado não reconhecido", "status": "UNKNOWN_STATE"})
    result = client.get(f"/api/v1/campaigns/{campaign_id}/readiness").json()
    codes = {item["code"] for item in result["blockers"]}
    assert {"DISCLOSURE_REQUIRED", "CHANNEL_REQUIRED", "ANGLE_REQUIRED", "EXPERIMENT_REQUIRED"} <= codes
    assert result["channelCount"] == result["angleCount"] == result["experimentCount"] == 0


def test_objectives_and_affiliate_link_verification_rules(client):
    cid, _ = campaign(client)
    assert client.patch(f"/api/v1/campaigns/{cid}", json={"objective": "MADE_UP"}).status_code == 422
    assert client.patch(f"/api/v1/campaigns/{cid}", json={"objective": None}).status_code == 422
    assert client.patch(f"/api/v1/campaigns/{cid}", json={"name": None}).status_code == 422
    client.patch(f"/api/v1/campaigns/{cid}", json={"objective": "CONVERSION"})
    assert "AFFILIATE_LINK_REQUIRED" in {x["code"] for x in client.get(f"/api/v1/campaigns/{cid}/readiness").json()["blockers"]}
    client.patch(f"/api/v1/campaigns/{cid}", json={"affiliateUrl": "https://example.com/item"})
    result = client.get(f"/api/v1/campaigns/{cid}/readiness").json()
    assert "AFFILIATE_LINK_NOT_VERIFIED" in {x["code"] for x in result["blockers"]}
    client.patch(f"/api/v1/campaigns/{cid}", json={"affiliateUrlVerified": True})
    assert client.get(f"/api/v1/campaigns/{cid}/readiness").json()["checks"]["affiliateLinkVerified"]
    education_id, _ = campaign(client, verdict="WORTH_IT")
    client.patch(f"/api/v1/campaigns/{education_id}", json={"targetAudience": "Público", "editorialPositioning": "Contextualizado", "primaryMessage": "Mensagem", "ctaStrategy": "Saiba mais"})
    assert "AFFILIATE_LINK_REQUIRED" not in {x["code"] for x in client.get(f"/api/v1/campaigns/{education_id}/readiness").json()["blockers"]}
    client.patch(f"/api/v1/campaigns/{education_id}", json={"affiliateUrl": "https://example.com", "affiliateUrlVerified": False})
    assert "AFFILIATE_LINK_NOT_VERIFIED" in {x["code"] for x in client.get(f"/api/v1/campaigns/{education_id}/readiness").json()["blockers"]}


def test_optional_objective_link_must_be_verified_and_validated_text_bounds(client):
    cid, _ = campaign(client, verdict="WORTH_IT")
    assert client.patch(f"/api/v1/campaigns/{cid}", json={"affiliateUrl": "https://example.com", "affiliateUrlVerified": True}).status_code == 200
    client.patch(f"/api/v1/campaigns/{cid}", json={"affiliateUrlVerified": False})
    result = client.get(f"/api/v1/campaigns/{cid}/readiness").json()
    assert "AFFILIATE_LINK_NOT_VERIFIED" in {x["code"] for x in result["blockers"]}
    assert client.patch(f"/api/v1/campaigns/{cid}", json={"primaryMessage": "x" * 2001}).status_code == 422
    assert client.patch(f"/api/v1/campaigns/{cid}", json={"assessmentId": "different"}).status_code == 422
    assert client.patch(f"/api/v1/campaigns/{cid}", json={"status": "APPROVED"}).status_code == 422


def test_invalid_experiment_channel_rejected_on_create_and_patch(client):
    cid, _ = campaign(client)
    assert client.post(f"/api/v1/campaigns/{cid}/experiments", json={"hypothesis": "Teste", "targetChannel": "TIKTOK"}).status_code == 422
    channel = client.post(f"/api/v1/campaigns/{cid}/channels", json={"channel": "TIKTOK"}).json()
    experiment = client.post(f"/api/v1/campaigns/{cid}/experiments", json={"hypothesis": "Teste"}).json()
    assert client.patch(f"/api/v1/campaigns/{cid}/experiments/{experiment['id']}", json={"targetChannel": "INSTAGRAM_REELS"}).status_code == 422
    assert client.patch(f"/api/v1/campaigns/{cid}/channels/{channel['id']}", json={"enabled": False}).status_code == 200


def test_financial_spend_is_warning_not_authorization(client):
    cid, _ = campaign(client); ready(client, cid)
    client.patch(f"/api/v1/campaigns/{cid}", json={"requiresFinancialSpend": True})
    result = client.get(f"/api/v1/campaigns/{cid}/readiness").json()
    assert result["state"] == "READY_FOR_APPROVAL"
    assert result["warnings"] == [{"code": "FINANCIAL_APPROVAL_REQUIRED", "message": "Qualquer gasto financeiro exigirá autorização separada antes da execução."}]


def test_submit_is_idempotent_and_records_a_complete_decision_once(client):
    cid, _ = campaign(client); ready(client, cid)
    first = client.post(f"/api/v1/campaigns/{cid}/submit-for-approval")
    assert first.status_code == 200
    second = client.post(f"/api/v1/campaigns/{cid}/submit-for-approval")
    assert second.status_code == 200 and second.json()["id"] == first.json()["id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_id == cid)) == 1
        logs = list(db.scalars(select(DecisionLog).where(DecisionLog.action == "CAMPAIGN_SUBMITTED", DecisionLog.entity_id == cid)))
        assert len(logs) == 1
        assert {"campaignId", "assessmentId", "readinessState", "approvalId", "requiresFinancialSpend", "channelCount", "angleCount", "experimentCount"} <= set(logs[0].metadata_)
    assert client.get(f"/api/v1/campaigns/{cid}").json()["status"] == "PENDING_APPROVAL"
    assert client.post(f"/api/v1/approvals/{first.json()['id']}/approve", json={}).status_code == 200
    approved_submit = client.post(f"/api/v1/campaigns/{cid}/submit-for-approval")
    assert approved_submit.status_code == 409 and approved_submit.json()["detail"]["code"] == "CAMPAIGN_ALREADY_APPROVED"


def test_submit_rejects_lifecycle_and_inconsistent_approval_states(client):
    cid, _ = campaign(client); ready(client, cid)
    first = client.post(f"/api/v1/campaigns/{cid}/submit-for-approval").json()
    with SessionLocal() as db:
        db.add(Approval(type="CAMPAIGN", status="PENDING", title="duplicada", description="", entity_type="CAMPAIGN", entity_id=cid)); db.commit()
    result = client.post(f"/api/v1/campaigns/{cid}/submit-for-approval")
    assert result.status_code == 409 and result.json()["detail"]["code"] == "CAMPAIGN_APPROVAL_STATE_INCONSISTENT"

    for status, code in (("PAUSED", "CAMPAIGN_PAUSED"), ("ARCHIVED", "CAMPAIGN_ARCHIVED")):
        other, _ = campaign(client); ready(client, other)
        with SessionLocal() as db:
            row = db.get(Campaign, other); row.status = status; db.commit()
        result = client.post(f"/api/v1/campaigns/{other}/submit-for-approval")
        assert result.status_code == 409 and result.json()["detail"]["code"] == code


def test_not_ready_submit_has_no_approval_status_change_or_decision_log(client):
    cid, _ = campaign(client)
    before = client.get(f"/api/v1/campaigns/{cid}").json()
    result = client.post(f"/api/v1/campaigns/{cid}/submit-for-approval")
    assert result.status_code == 409 and result.json()["detail"]["code"] == "CAMPAIGN_NOT_READY"
    assert result.json()["detail"]["blockers"]
    after = client.get(f"/api/v1/campaigns/{cid}").json()
    assert after["status"] == before["status"] == "DRAFT"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_id == cid)) == 0
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "CAMPAIGN_SUBMITTED", DecisionLog.entity_id == cid)) == 0


def test_campaign_readiness_semantically_reports_non_draft_lifecycle(client):
    cid, _ = campaign(client)
    for status in ("PENDING_APPROVAL", "APPROVED", "PAUSED", "ARCHIVED"):
        with SessionLocal() as db:
            row = db.get(Campaign, cid); row.status = status; db.commit()
        result = client.get(f"/api/v1/campaigns/{cid}/readiness").json()
        assert result["state"] == status and result["campaignStatus"] == status

