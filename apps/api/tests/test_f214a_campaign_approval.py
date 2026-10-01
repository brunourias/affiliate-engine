from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from sqlalchemy import func, select

from apps.api.app.db.models import (
    Approval, Campaign, CuratorAssessment, Creative, CreativeScene, DecisionLog,
    MediaJob, Notification, PublicationExecution,
)
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.campaigns import readiness
from apps.api.app.services.campaign_approval_decisions import CampaignApprovalDecisionService
from apps.api.tests.test_v1d_campaigns import create, ready


def submitted(client, **kwargs):
    response, assessment_id = create(client, **kwargs)
    assert response.status_code == 201
    campaign_id = response.json()["id"]
    ready(client, campaign_id)
    approval_response = client.post(f"/api/v1/campaigns/{campaign_id}/submit-for-approval")
    assert approval_response.status_code == 200
    return campaign_id, assessment_id, approval_response.json()


def counts(campaign_id):
    with SessionLocal() as db:
        return {
            "approvals": db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_id == campaign_id)) or 0,
            "notifications": db.scalar(select(func.count()).select_from(Notification).where(Notification.type == "APPROVAL")) or 0,
            "logs": db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.entity_type.in_(["APPROVAL", "CAMPAIGN"]))) or 0,
            "creatives": db.scalar(select(func.count()).select_from(Creative)) or 0,
            "scenes": db.scalar(select(func.count()).select_from(CreativeScene)) or 0,
            "media_jobs": db.scalar(select(func.count()).select_from(MediaJob)) or 0,
            "publication_executions": db.scalar(select(func.count()).select_from(PublicationExecution)) or 0,
        }


def test_campaign_approve_updates_both_records_timestamps_and_exactly_one_audit_set(client):
    campaign_id, _, approval = submitted(client)
    with SessionLocal() as db:
        db.get(Campaign, campaign_id).rejected_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        db.commit()
    response = client.post(f"/api/v1/approvals/{approval['id']}/approve", json={"reason": "  aprovado  "})
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert response.json()["decisionReason"] == "aprovado"
    assert response.json()["decidedAt"]
    with SessionLocal() as db:
        campaign = db.get(Campaign, campaign_id)
        stored = db.get(Approval, approval["id"])
        assert campaign.status == stored.status == "APPROVED"
        assert campaign.approved_at and campaign.rejected_at is None
        assert stored.decided_at and stored.decision_reason == "aprovado"
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "APPROVAL_APPROVED", DecisionLog.entity_id == stored.id)) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "CAMPAIGN_APPROVED", DecisionLog.entity_id == campaign_id)) == 1
        approval_log = db.scalar(select(DecisionLog).where(DecisionLog.action == "APPROVAL_APPROVED", DecisionLog.entity_id == stored.id))
        campaign_log = db.scalar(select(DecisionLog).where(DecisionLog.action == "CAMPAIGN_APPROVED", DecisionLog.entity_id == campaign_id))
        assert {"type": "CAMPAIGN", "entityType": "CAMPAIGN", "entityId": campaign_id} == approval_log.metadata_
        assert {"approvalId": stored.id, "campaignId": campaign_id, "assessmentId": campaign.assessment_id} == campaign_log.metadata_
        note = db.scalar(select(Notification).where(Notification.type == "APPROVAL"))
        assert note.metadata_ == {"approvalId": stored.id}
        assert readiness(db, campaign)["state"] == "APPROVED"
        assert readiness(db, campaign)["nextAction"] == "NONE"


def test_campaign_approve_replay_is_read_only_and_conflicting_decision_is_409(client):
    campaign_id, _, approval = submitted(client)
    url = f"/api/v1/approvals/{approval['id']}/approve"
    first = client.post(url, json={"reason": "ok"}).json()
    before = counts(campaign_id)
    second = client.post(url, json={"reason": "different"})
    assert second.status_code == 200 and second.json() == first
    assert counts(campaign_id) == before
    conflict = client.post(f"/api/v1/approvals/{approval['id']}/reject", json={})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "APPROVAL_DECISION_CONFLICT"
    assert conflict.json()["detail"]["currentStatus"] == "APPROVED"


def test_campaign_reject_updates_reason_timestamps_and_replay_without_duplicate_effects(client):
    campaign_id, _, approval = submitted(client)
    with SessionLocal() as db:
        db.get(Campaign, campaign_id).approved_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        db.commit()
    url = f"/api/v1/approvals/{approval['id']}/reject"
    first = client.post(url, json={"reason": "  corrigir  "})
    assert first.status_code == 200 and first.json()["decisionReason"] == "corrigir"
    with SessionLocal() as db:
        campaign = db.get(Campaign, campaign_id)
        assert campaign.status == "REJECTED" and campaign.rejected_at and campaign.approved_at is None
        assert readiness(db, campaign)["nextAction"] == "READY_TO_SUBMIT"
    before = counts(campaign_id)
    second = client.post(url, json={"reason": "outro"})
    assert second.status_code == 200 and second.json() == first.json()
    assert counts(campaign_id) == before
    assert client.post(f"/api/v1/approvals/{approval['id']}/approve", json={}).json()["detail"]["code"] == "APPROVAL_DECISION_CONFLICT"


@pytest.mark.parametrize("entity_type,entity_id", [("CREATIVE", "missing"), (None, "missing"), ("CAMPAIGN", None)])
def test_malformed_campaign_approval_is_not_decided(client, entity_type, entity_id):
    with SessionLocal() as db:
        item = Approval(type="CAMPAIGN", title="Malformed", description="", entity_type=entity_type, entity_id=entity_id)
        db.add(item); db.commit(); item_id = item.id
    before = counts("missing")
    result = client.post(f"/api/v1/approvals/{item_id}/approve", json={})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "CAMPAIGN_APPROVAL_STATE_INCONSISTENT"
    with SessionLocal() as db:
        assert db.get(Approval, item_id).status == "PENDING"
    assert counts("missing") == before


def test_campaign_approval_requires_existing_campaign_pending_status_and_exactly_one_pending(client):
    campaign_id, _, _ = submitted(client)
    with SessionLocal() as db:
        orphan = Approval(type="CAMPAIGN", title="Orphan", description="", entity_type="CAMPAIGN", entity_id="missing-campaign")
        db.add(orphan); db.commit(); orphan_id = orphan.id
    result = client.post(f"/api/v1/approvals/{orphan_id}/approve", json={})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "CAMPAIGN_APPROVAL_STATE_INCONSISTENT"
    with SessionLocal() as db:
        assert db.get(Approval, orphan_id).status == "PENDING"
        db.get(Campaign, campaign_id).status = "DRAFT"
        db.commit()
        pending_id = db.scalar(select(Approval.id).where(Approval.entity_id == campaign_id, Approval.status == "PENDING"))
    result = client.post(f"/api/v1/approvals/{pending_id}/approve", json={})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "CAMPAIGN_APPROVAL_STATE_INCONSISTENT"


@pytest.mark.parametrize("pending_count", [0, 2])
def test_campaign_approval_rejects_zero_or_multiple_pending_approvals(client, pending_count):
    campaign_id, _, approval = submitted(client)
    with SessionLocal() as db:
        original = db.get(Approval, approval["id"])
        if pending_count == 0:
            original.status = "REJECTED"
        else:
            db.add(Approval(type="CAMPAIGN", title="Outra pendente", description="", entity_type="CAMPAIGN", entity_id=campaign_id))
        db.commit()
    result = client.post(f"/api/v1/approvals/{approval['id']}/approve", json={})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "CAMPAIGN_APPROVAL_STATE_INCONSISTENT"


def test_campaign_status_must_be_pending_and_historical_decisions_are_ignored(client):
    campaign_id, _, first = submitted(client)
    assert client.post(f"/api/v1/approvals/{first['id']}/reject", json={}).status_code == 200
    with SessionLocal() as db:
        campaign = db.get(Campaign, campaign_id)
        assert campaign.status == "REJECTED"
        campaign.status = "PENDING_APPROVAL"
        second = Approval(type="CAMPAIGN", title="Segundo ciclo", description="", entity_type="CAMPAIGN", entity_id=campaign_id)
        db.add(second); db.commit(); second_id = second.id
    assert client.post(f"/api/v1/approvals/{second_id}/approve", json={}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Approval, first["id"]).status == "REJECTED"
        assert db.get(Approval, second_id).status == "APPROVED"
        assert db.get(Campaign, campaign_id).status == "APPROVED"


def _add_current_assessment(candidate_id, previous_id):
    with SessionLocal() as db:
        previous = db.get(CuratorAssessment, previous_id)
        values = {column.name: getattr(previous, column.name) for column in CuratorAssessment.__table__.columns if column.name not in {"id", "created_at"}}
        values.update(assessment_version=previous.assessment_version + 1, previous_assessment_id=previous.id)
        latest = CuratorAssessment(**values)
        db.add(latest); db.commit(); return latest.id


def test_approve_revalidates_current_readiness_but_reject_remains_available(client):
    campaign_id, assessment_id, approval = submitted(client)
    _add_current_assessment(None, assessment_id)
    result = client.post(f"/api/v1/approvals/{approval['id']}/approve", json={})
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "CAMPAIGN_APPROVAL_INVALIDATED"
    assert "ASSESSMENT_OUTDATED" in {item["code"] for item in result.json()["detail"]["blockers"]}
    with SessionLocal() as db:
        assert db.get(Approval, approval["id"]).status == "PENDING"
        assert db.get(Campaign, campaign_id).status == "PENDING_APPROVAL"
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action.in_(["APPROVAL_APPROVED", "CAMPAIGN_APPROVED"]))) == 0
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.type == "APPROVAL")) == 0
    assert client.post(f"/api/v1/approvals/{approval['id']}/reject", json={"reason": "análise desatualizada"}).status_code == 200


def test_approve_revalidation_blocks_other_current_readiness_blockers(client):
    campaign_id, _, approval = submitted(client)
    with SessionLocal() as db:
        db.get(Campaign, campaign_id).target_audience = None
        db.commit()
    result = client.post(f"/api/v1/approvals/{approval['id']}/approve", json={})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "CAMPAIGN_APPROVAL_INVALIDATED"
    assert "TARGET_AUDIENCE_REQUIRED" in {item["code"] for item in result.json()["detail"]["blockers"]}


def test_rejected_campaign_can_be_corrected_resubmitted_and_second_approval_succeeds(client):
    campaign_id, assessment_id, first = submitted(client)
    assert client.post(f"/api/v1/approvals/{first['id']}/reject", json={"reason": "ajustar"}).status_code == 200
    assert client.patch(f"/api/v1/campaigns/{campaign_id}", json={"primaryMessage": "Mensagem revisada"}).status_code == 200
    second_response = client.post(f"/api/v1/campaigns/{campaign_id}/submit-for-approval")
    assert second_response.status_code == 200
    second = second_response.json()
    assert second["id"] != first["id"] and second["status"] == "PENDING"
    replay = client.post(f"/api/v1/campaigns/{campaign_id}/submit-for-approval")
    assert replay.status_code == 200 and replay.json()["id"] == second["id"]
    assert client.post(f"/api/v1/approvals/{second['id']}/approve", json={}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Approval, first["id"]).status == "REJECTED"
        assert db.get(Approval, second["id"]).status == "APPROVED"
        assert db.get(Campaign, campaign_id).status == "APPROVED"
        assert db.get(Campaign, campaign_id).assessment_id == assessment_id
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_type == "CAMPAIGN", Approval.entity_id == campaign_id)) == 2


def test_decision_effect_failure_rolls_back_approval_campaign_logs_and_notification(client, monkeypatch):
    campaign_id, _, approval = submitted(client)
    import apps.api.app.services.campaign_approval_decisions as decision_service

    def fail_notification(*args, **kwargs):
        raise RuntimeError("simulated notification insert failure")

    monkeypatch.setattr(decision_service, "notify", fail_notification)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="simulated notification"):
            CampaignApprovalDecisionService(db).decide(approval["id"], "APPROVED")
    with SessionLocal() as db:
        assert db.get(Approval, approval["id"]).status == "PENDING"
        assert db.get(Campaign, campaign_id).status == "PENDING_APPROVAL"
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action.in_(["APPROVAL_APPROVED", "CAMPAIGN_APPROVED"]))) == 0
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.type == "APPROVAL")) == 0


def test_approval_decision_never_creates_creative_media_or_publication_records(client):
    campaign_id, _, approval = submitted(client)
    before = counts(campaign_id)
    assert client.post(f"/api/v1/approvals/{approval['id']}/approve", json={}).status_code == 200
    after = counts(campaign_id)
    for key in ("creatives", "scenes", "media_jobs", "publication_executions"):
        assert after[key] == before[key] == 0


def test_concurrent_approve_approve_converges_to_one_decision_effect_set(client):
    campaign_id, _, approval = submitted(client)
    barrier = Barrier(2)

    def decide():
        with SessionLocal() as db:
            item = db.get(Approval, approval["id"])
            barrier.wait(timeout=5)
            try:
                return CampaignApprovalDecisionService(db).decide(item.id, "APPROVED").status
            except Exception:
                db.rollback()
                raise

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: decide(), range(2)))
    assert results == ["APPROVED", "APPROVED"]
    with SessionLocal() as db:
        assert db.get(Campaign, campaign_id).status == "APPROVED"
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "APPROVAL_APPROVED", DecisionLog.entity_id == approval["id"])) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "CAMPAIGN_APPROVED", DecisionLog.entity_id == campaign_id)) == 1
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.type == "APPROVAL")) == 1


def test_concurrent_approve_reject_has_one_consistent_winner(client):
    campaign_id, _, approval = submitted(client)
    barrier = Barrier(2)

    def decide(status):
        with SessionLocal() as db:
            item = db.get(Approval, approval["id"])
            barrier.wait(timeout=5)
            try:
                return CampaignApprovalDecisionService(db).decide(item.id, status).status
            except Exception as exc:
                db.rollback()
                if getattr(exc, "status_code", None) == 409:
                    return "CONFLICT"
                raise

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ["APPROVED", "REJECTED"]))
    assert results.count("CONFLICT") == 1
    winner = "APPROVED" if results[0] == "APPROVED" else "REJECTED"
    with SessionLocal() as db:
        assert db.get(Approval, approval["id"]).status == winner
        campaign = db.get(Campaign, campaign_id)
        assert campaign.status == winner
        assert (campaign.approved_at is not None) == (winner == "APPROVED")
        assert (campaign.rejected_at is not None) == (winner == "REJECTED")
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.type == "APPROVAL")) == 1


def test_creative_approval_remains_supported_by_generic_decision_flow(client):
    campaign_id, _, _ = submitted(client)
    # The existing Creative approval integration regression is also exercised in
    # test_v1e_creatives; this assertion guards that Campaign dispatch is scoped.
    with SessionLocal() as db:
        item = Approval(type="CREATIVE", title="Creative review", description="", entity_type="CREATIVE", entity_id="missing")
        db.add(item); db.commit(); item_id = item.id
    response = client.post(f"/api/v1/approvals/{item_id}/approve", json={})
    assert response.status_code == 200 and response.json()["status"] == "APPROVED"
    assert client.get(f"/api/v1/campaigns/{campaign_id}").json()["status"] == "PENDING_APPROVAL"
