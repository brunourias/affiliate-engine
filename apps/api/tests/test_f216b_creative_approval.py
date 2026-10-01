from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from apps.api.app.db.models import (
    Approval, Campaign, CampaignAngle, CampaignChannel, CampaignExperiment,
    Creative, CreativeScene, CuratorAssessment, CuratorCandidate, DecisionLog,
    MediaJob, Notification, PublicationExecution,
)
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.creatives import readiness as creative_readiness
from apps.api.app.services.creative_approval_decisions import CreativeApprovalDecisionService


def make_campaign(status="APPROVED", warnings=None):
    with SessionLocal() as db:
        candidate = CuratorCandidate(provider="OTHER", source_type="MANUAL", entity_type="MANUAL", working_title="Produto teste")
        db.add(candidate)
        db.flush()
        assessment = CuratorAssessment(candidate_id=candidate.id, assessment_version=1, evidence_status="SUFFICIENT",
            evidence_level="PUBLIC_VERIFIED", trust_gate="PASS", trust_reasons=[], trust_warnings=[],
            recommendation_score=80, recommendation_coverage_percent=100, recommendation_label="GOOD",
            opportunity_score=70, opportunity_coverage_percent=100, price_verdict="FAIR_PRICE",
            editorial_verdict="WORTH_IT", recommendation_pillars={}, opportunity_pillars={},
            evidence_ids_used=[], unknown_fields=[], rationale={})
        db.add(assessment)
        db.flush()
        campaign = Campaign(candidate_id=candidate.id, assessment_id=assessment.id, name="Produto teste", status=status,
            objective="EDUCATION", editorial_verdict_snapshot="WORTH_IT", trust_gate_snapshot="PASS",
            recommendation_score_snapshot=80, opportunity_score_snapshot=70, price_verdict_snapshot="FAIR_PRICE",
            campaign_priority="HIGH", target_audience="Público", editorial_positioning="Posicionamento",
            primary_message="Mensagem", cta_strategy="Veja detalhes", disclosure_text="Aviso de afiliação",
            trust_warnings_snapshot=warnings or [], required_disclosures=[], required_warnings=warnings or [], forbidden_claims=[])
        db.add(campaign)
        db.flush()
        db.add(CampaignChannel(campaign_id=campaign.id, channel="TIKTOK", enabled=True))
        db.flush()
        angle = CampaignAngle(campaign_id=campaign.id, angle_type="SMART_BUYING", title="Ângulo", premise="Compare", status="ACTIVE")
        db.add(angle)
        db.flush()
        db.add(CampaignExperiment(campaign_id=campaign.id, angle_id=angle.id, hypothesis="Hipótese", status="PLANNED", target_channel="TIKTOK"))
        if status == "APPROVED":
            db.add(Approval(type="CAMPAIGN", status="APPROVED", title="Campanha aprovada", description="Snapshot", entity_type="CAMPAIGN", entity_id=campaign.id, requested_payload={}))
        db.commit()
        return campaign.id


def make_creative(client, *, ready=True, campaign_status="APPROVED", warnings=None):
    campaign_id = make_campaign(campaign_status, warnings)
    response = client.post(f"/api/v1/creatives/from-campaign/{campaign_id}", json={})
    assert response.status_code == 201, response.text
    creative_id = response.json()["id"]
    if not ready:
        client.patch(f"/api/v1/creatives/{creative_id}", json={"cta": None})
    if ready:
        patch = client.patch(f"/api/v1/creatives/{creative_id}", json={
            "hook": "Veja o que considerar.", "bodyScript": "Informações disponíveis para comparar.", "cta": "Confira os detalhes.",
        })
        assert patch.status_code == 200, patch.text
        warning_text = (warnings or [{}])[0].get("message", "") if warnings else ""
        scene = client.post(f"/api/v1/creatives/{creative_id}/scenes", json={
            "orderIndex": 0, "sceneType": "TEXT", "purpose": "REVIEW",
            "narrationText": warning_text or "Informações para comparar.",
        })
        assert scene.status_code == 201, scene.text
    return campaign_id, creative_id


def submit(client, creative_id):
    return client.post(f"/api/v1/creatives/{creative_id}/submit-for-review", json={})


def test_readiness_contract_blockers_and_complete_content_action(client):
    _, creative_id = make_creative(client, ready=False)
    result = client.get(f"/api/v1/creatives/{creative_id}/readiness").json()
    assert {"state", "checks", "sceneCount", "compliance", "creativeStatus", "blockers", "warnings", "nextAction"} <= result.keys()
    assert {item["code"] for item in result["blockers"]} >= {"HOOK_REQUIRED", "BODY_SCRIPT_REQUIRED", "CTA_REQUIRED", "SCENE_REQUIRED"}
    assert all({"code", "message"} <= blocker.keys() for blocker in result["blockers"])
    assert result["nextAction"] == "COMPLETE_CONTENT"
    assert submit(client, creative_id).status_code == 409


def test_readiness_actions_scene_compliance_and_ready_to_submit(client):
    _, creative_id = make_creative(client, ready=False)
    client.patch(f"/api/v1/creatives/{creative_id}", json={"hook": "Hook", "bodyScript": "Roteiro", "cta": "CTA"})
    result = client.get(f"/api/v1/creatives/{creative_id}/readiness").json()
    assert result["nextAction"] == "ADD_SCENE"
    client.post(f"/api/v1/creatives/{creative_id}/scenes", json={"orderIndex": 0, "sceneType": "TEXT", "purpose": "Review", "narrationText": "Cena"})
    with SessionLocal() as db:
        creative = db.get(Creative, creative_id)
        creative.forbidden_claims = ["BEST_ON_MARKET_UNSUPPORTED"]
        creative.hook = "A melhor parafusadeira do mercado"
        db.commit()
    assert client.get(f"/api/v1/creatives/{creative_id}/readiness").json()["nextAction"] == "RESOLVE_COMPLIANCE"
    client.patch(f"/api/v1/creatives/{creative_id}", json={"hook": "Compare as informações disponíveis"})
    ready = client.get(f"/api/v1/creatives/{creative_id}/readiness").json()
    assert ready["state"] == "READY_FOR_REVIEW" and ready["nextAction"] == "READY_TO_SUBMIT"


def test_readiness_requires_exactly_approved_current_campaign_and_context(client):
    campaign_id, creative_id = make_creative(client)
    with SessionLocal() as db:
        db.get(Campaign, campaign_id).status = "PAUSED"
        db.commit()
    result = client.get(f"/api/v1/creatives/{creative_id}/readiness").json()
    assert result["checks"]["campaignApproved"] is False
    assert result["nextAction"] == "REVIEW_CAMPAIGN_CONTEXT"
    assert any(b["code"] == "CAMPAIGN_NOT_APPROVED" for b in result["blockers"])
    assert submit(client, creative_id).status_code == 409


def test_new_assessment_invalidates_campaign_context_for_submit_and_approve(client):
    campaign_id, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    with SessionLocal() as db:
        campaign = db.get(Campaign, campaign_id)
        source = db.get(CuratorAssessment, campaign.assessment_id)
        newer = CuratorAssessment(candidate_id=source.candidate_id, assessment_version=2, evidence_status="SUFFICIENT",
            evidence_level="PUBLIC_VERIFIED", trust_gate="PASS", trust_reasons=[], trust_warnings=[],
            recommendation_score=81, recommendation_coverage_percent=100, recommendation_label="GOOD",
            opportunity_score=71, opportunity_coverage_percent=100, price_verdict="FAIR_PRICE",
            editorial_verdict="WORTH_IT", recommendation_pillars={}, opportunity_pillars={}, evidence_ids_used=[], unknown_fields=[], rationale={})
        db.add(newer)
        db.commit()
    ready = client.get(f"/api/v1/creatives/{creative_id}/readiness").json()
    assert ready["nextAction"] == "REVIEW_CAMPAIGN_CONTEXT"
    assert any(b["code"] == "CAMPAIGN_CONTEXT_INVALIDATED" for b in ready["blockers"])
    rejected = client.post(f"/api/v1/approvals/{approval['id']}/approve", json={})
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "CREATIVE_APPROVAL_INVALIDATED"
    with SessionLocal() as db:
        assert db.get(Approval, approval["id"]).status == "PENDING"
        assert db.get(Creative, creative_id).status == "READY_FOR_REVIEW"
    assert client.post(f"/api/v1/approvals/{approval['id']}/reject", json={"reason": "Não seguir"}).status_code == 200


def test_legacy_origin_warns_but_does_not_block(client):
    _, creative_id = make_creative(client)
    with SessionLocal() as db:
        creative = db.get(Creative, creative_id)
        creative.creation_source = None
        creative.source_campaign_approval_id = None
        creative.source_assessment_id = None
        db.commit()
    result = client.get(f"/api/v1/creatives/{creative_id}/readiness").json()
    assert result["state"] == "READY_FOR_REVIEW"
    assert any(w["code"] == "LEGACY_CREATIVE_ORIGIN_UNTRACKED" for w in result["warnings"])
    assert not any(b["code"] == "SOURCE_CAMPAIGN_APPROVAL_INVALID" for b in result["blockers"])


def test_invalid_controlled_origin_blocks_readiness(client):
    _, creative_id = make_creative(client)
    with SessionLocal() as db:
        db.get(Creative, creative_id).source_campaign_approval_id = None
        db.commit()
    result = client.get(f"/api/v1/creatives/{creative_id}/readiness").json()
    assert any(b["code"] == "SOURCE_CAMPAIGN_APPROVAL_INVALID" for b in result["blockers"])
    assert result["nextAction"] == "REVIEW_CAMPAIGN_CONTEXT"


def test_wrong_source_assessment_blocks_controlled_creative(client):
    campaign_id, creative_id = make_creative(client)
    with SessionLocal() as db:
        campaign = db.get(Campaign, campaign_id)
        candidate = db.get(CuratorCandidate, campaign.candidate_id)
        other = CuratorAssessment(candidate_id=candidate.id, assessment_version=2, evidence_status="SUFFICIENT",
            evidence_level="PUBLIC_VERIFIED", trust_gate="PASS", trust_reasons=[], trust_warnings=[],
            recommendation_score=80, recommendation_coverage_percent=100, recommendation_label="GOOD",
            opportunity_score=70, opportunity_coverage_percent=100, price_verdict="FAIR_PRICE",
            editorial_verdict="WORTH_IT", recommendation_pillars={}, opportunity_pillars={}, evidence_ids_used=[], unknown_fields=[], rationale={})
        db.add(other)
        db.commit()
        db.get(Creative, creative_id).source_assessment_id = other.id
        db.commit()
    result = client.get(f"/api/v1/creatives/{creative_id}/readiness").json()
    assert any(b["code"] == "SOURCE_ASSESSMENT_INVALID" for b in result["blockers"])
    assert result["nextAction"] == "REVIEW_CAMPAIGN_CONTEXT"


@pytest.mark.parametrize("status,expected", [("APPROVED", "CREATIVE_ALREADY_APPROVED"), ("ARCHIVED", "CREATIVE_ARCHIVED"), ("PENDING_APPROVAL", "CREATIVE_STATUS_NOT_SUBMITTABLE")])
def test_submit_rejects_terminal_or_unexpected_statuses(client, status, expected):
    _, creative_id = make_creative(client)
    with SessionLocal() as db:
        db.get(Creative, creative_id).status = status
        db.commit()
    response = submit(client, creative_id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == expected


def test_submit_ready_creates_auditable_snapshot_and_zero_side_effect_payload(client):
    _, creative_id = make_creative(client)
    response = submit(client, creative_id)
    assert response.status_code == 200, response.text
    approval = response.json()
    assert approval["type"] == "CREATIVE" and approval["status"] == "PENDING"
    for label in ("Criativo:", "Campanha:", "Formato:", "Canal:", "Premissa:", "Hook:", "Roteiro:", "CTA:", "Cenas:", "Aviso de afiliação:", "Compliance:", "Modo de geração:"):
        assert label in approval["description"]
    assert approval["requestedPayload"]["rendersMedia"] is False
    assert approval["requestedPayload"]["publishes"] is False
    assert approval["requestedPayload"]["financialSpend"] is False
    assert approval["requestedPayload"]["sceneCount"] == 1
    with SessionLocal() as db:
        logs = list(db.scalars(select(DecisionLog).where(DecisionLog.entity_id == creative_id, DecisionLog.action == "CREATIVE_SUBMITTED")))
        assert len(logs) == 1
        assert logs[0].metadata_["approvalId"] == approval["id"]
        assert db.get(Creative, creative_id).status == "READY_FOR_REVIEW"


def test_submit_replay_is_read_only_and_inconsistent_states_are_rejected(client):
    _, creative_id = make_creative(client)
    first = submit(client, creative_id).json()
    replay = submit(client, creative_id).json()
    assert replay["id"] == first["id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_id == creative_id, Approval.status == "PENDING")) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.entity_id == creative_id, DecisionLog.action == "CREATIVE_SUBMITTED")) == 1
        duplicate = Approval(type="CREATIVE", status="PENDING", title="Duplicate", description="", entity_type="CREATIVE", entity_id=creative_id, requested_payload={})
        db.add(duplicate)
        db.commit()
    assert submit(client, creative_id).json()["detail"]["code"] == "CREATIVE_APPROVAL_STATE_INCONSISTENT"


def test_ready_for_review_without_pending_is_inconsistent(client):
    _, creative_id = make_creative(client)
    with SessionLocal() as db:
        db.get(Creative, creative_id).status = "READY_FOR_REVIEW"
        db.commit()
    response = submit(client, creative_id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "CREATIVE_APPROVAL_STATE_INCONSISTENT"


def test_draft_with_unexpected_pending_approval_does_not_create_another(client):
    _, creative_id = make_creative(client)
    with SessionLocal() as db:
        db.add(Approval(type="CREATIVE", status="PENDING", title="Pendência órfã", description="", entity_type="CREATIVE", entity_id=creative_id, requested_payload={}))
        db.commit()
    response = submit(client, creative_id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "CREATIVE_APPROVAL_STATE_INCONSISTENT"
    with SessionLocal() as db:
        assert db.get(Creative, creative_id).status == "DRAFT"
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_id == creative_id, Approval.status == "PENDING")) == 1


def test_submit_rolls_back_status_when_approval_or_log_insert_fails(client, monkeypatch):
    _, creative_id = make_creative(client)
    from apps.api.app.services import creatives as creative_service
    monkeypatch.setattr(creative_service, "log_decision", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("log failure")))
    with pytest.raises(RuntimeError):
        submit(client, creative_id)
    with SessionLocal() as db:
        assert db.get(Creative, creative_id).status == "DRAFT"
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_id == creative_id, Approval.type == "CREATIVE")) == 0


def test_submit_concurrent_requests_converge_to_one_pending_approval(client):
    _, creative_id = make_creative(client)
    barrier = Barrier(2)
    def run():
        with SessionLocal() as db:
            creative = db.get(Creative, creative_id)
            barrier.wait()
            return __import__("apps.api.app.services.creatives", fromlist=["submit"]).submit(db, creative).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results[0] == results[1]
    with SessionLocal() as db:
        assert db.get(Creative, creative_id).status == "READY_FOR_REVIEW"
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_id == creative_id, Approval.status == "PENDING")) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.entity_id == creative_id, DecisionLog.action == "CREATIVE_SUBMITTED")) == 1


def test_approve_and_reject_transition_pair_reason_replay_and_conflict(client):
    _, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    approved = client.post(f"/api/v1/approvals/{approval['id']}/approve", json={"reason": "  Revisão aprovada  "}).json()
    replay = client.post(f"/api/v1/approvals/{approval['id']}/approve", json={"reason": "outro motivo"}).json()
    assert approved["decisionReason"] == "Revisão aprovada"
    assert replay["decisionReason"] == approved["decisionReason"] and replay["decidedAt"] == approved["decidedAt"] and replay["updatedAt"] == approved["updatedAt"]
    with SessionLocal() as db:
        creative = db.get(Creative, creative_id)
        assert creative.status == "APPROVED" and creative.approved_at and creative.rejected_at is None
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.type == "APPROVAL")) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "APPROVAL_APPROVED")) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "CREATIVE_APPROVED")) == 1
    conflict = client.post(f"/api/v1/approvals/{approval['id']}/reject", json={})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "APPROVAL_DECISION_CONFLICT"
    approved_readiness = client.get(f"/api/v1/creatives/{creative_id}/readiness").json()
    assert approved_readiness["state"] == "APPROVED" and approved_readiness["nextAction"] == "NONE"


def test_reject_replay_is_read_only_and_approved_creative_is_not_editable(client):
    _, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    first = client.post(f"/api/v1/approvals/{approval['id']}/reject", json={"reason": "  Revisar  "}).json()
    replay = client.post(f"/api/v1/approvals/{approval['id']}/reject", json={"reason": "novo"}).json()
    assert replay["decisionReason"] == "Revisar" and replay["decidedAt"] == first["decidedAt"] and replay["updatedAt"] == first["updatedAt"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.type == "APPROVAL")) == 1
    second = submit(client, creative_id).json()
    assert client.post(f"/api/v1/approvals/{second['id']}/approve", json={}).status_code == 200
    assert client.patch(f"/api/v1/creatives/{creative_id}", json={"hook": "Não editar"}).status_code == 409


def test_compliance_change_after_submit_invalidates_approve_but_allows_reject(client):
    _, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    with SessionLocal() as db:
        creative = db.get(Creative, creative_id)
        creative.forbidden_claims = ["BEST_ON_MARKET_UNSUPPORTED"]
        creative.hook = "Esta é a melhor parafusadeira do mercado."
        db.commit()
    response = client.post(f"/api/v1/approvals/{approval['id']}/approve", json={})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "CREATIVE_APPROVAL_INVALIDATED"
    assert client.post(f"/api/v1/approvals/{approval['id']}/reject", json={}).status_code == 200


def test_warning_coverage_is_a_structured_readiness_blocker(client):
    warning = {"code": "LIMITATION", "message": "Uso doméstico"}
    _, creative_id = make_creative(client, ready=False, warnings=[warning])
    client.patch(f"/api/v1/creatives/{creative_id}", json={"hook": "Hook", "bodyScript": "Roteiro", "cta": "CTA"})
    client.post(f"/api/v1/creatives/{creative_id}/scenes", json={"orderIndex": 0, "sceneType": "TEXT", "purpose": "Review", "narrationText": "Conteúdo neutro"})
    result = client.get(f"/api/v1/creatives/{creative_id}/readiness").json()
    assert any(blocker["code"] == "WARNING_COVERAGE_REQUIRED" for blocker in result["blockers"])
    assert result["nextAction"] == "RESOLVE_COMPLIANCE"
def test_reject_keeps_creative_editable_then_new_cycle_preserves_history(client):
    _, creative_id = make_creative(client)
    first = submit(client, creative_id).json()
    rejected = client.post(f"/api/v1/approvals/{first['id']}/reject", json={"reason": "  Ajustar  "}).json()
    assert rejected["decisionReason"] == "Ajustar"
    with SessionLocal() as db:
        creative = db.get(Creative, creative_id)
        assert creative.status == "REJECTED" and creative.rejected_at and creative.approved_at is None
    assert client.patch(f"/api/v1/creatives/{creative_id}", json={"hook": "Hook revisado"}).status_code == 200
    second = submit(client, creative_id).json()
    assert second["id"] != first["id"]
    assert submit(client, creative_id).json()["id"] == second["id"]
    assert client.post(f"/api/v1/approvals/{second['id']}/approve", json={}).status_code == 200
    with SessionLocal() as db:
        history = list(db.scalars(select(Approval).where(Approval.entity_id == creative_id, Approval.type == "CREATIVE").order_by(Approval.created_at, Approval.id)))
        assert [(item.id, item.status) for item in history] == [(first["id"], "REJECTED"), (second["id"], "APPROVED")]


@pytest.mark.parametrize("corruption", ["wrong_entity_type", "null_entity", "missing_creative", "draft_creative", "no_pending", "multiple_pending"])
def test_malformed_approval_is_rejected_without_mutation(client, corruption):
    _, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    with SessionLocal() as db:
        item = db.get(Approval, approval["id"])
        if corruption == "wrong_entity_type": item.entity_type = "CAMPAIGN"
        elif corruption == "null_entity": item.entity_id = None
        elif corruption == "missing_creative":
            item.entity_id = "missing-creative"
        elif corruption == "draft_creative": db.get(Creative, creative_id).status = "DRAFT"
        elif corruption == "no_pending": item.status = "REJECTED"
        elif corruption == "multiple_pending":
            db.add(Approval(type="CREATIVE", status="PENDING", title="Duplicada", description="", entity_type="CREATIVE", entity_id=creative_id, requested_payload={}))
        db.commit()
    response = client.post(f"/api/v1/approvals/{approval['id']}/approve", json={})
    assert response.status_code == 409
    expected = "APPROVAL_DECISION_CONFLICT" if corruption == "no_pending" else "CREATIVE_APPROVAL_STATE_INCONSISTENT"
    assert response.json()["detail"]["code"] == expected
    with SessionLocal() as db:
        expected_status = "DRAFT" if corruption == "draft_creative" else "READY_FOR_REVIEW"
        assert db.get(Creative, creative_id).status == expected_status


def test_approve_revalidation_failure_rolls_back_but_reject_remains_available(client):
    campaign_id, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    with SessionLocal() as db:
        db.get(Campaign, campaign_id).status = "PAUSED"
        db.commit()
    response = client.post(f"/api/v1/approvals/{approval['id']}/approve", json={})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "CREATIVE_APPROVAL_INVALIDATED"
    with SessionLocal() as db:
        assert db.get(Approval, approval["id"]).status == "PENDING"
        assert db.get(Creative, creative_id).status == "READY_FOR_REVIEW"
        assert db.scalar(select(func.count()).select_from(Notification)) == 0
    assert client.post(f"/api/v1/approvals/{approval['id']}/reject", json={}).status_code == 200


def test_decision_side_effect_failure_rolls_back_everything(client, monkeypatch):
    _, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    from apps.api.app.services import creative_approval_decisions
    monkeypatch.setattr(creative_approval_decisions, "notify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("notification failure")))
    with pytest.raises(RuntimeError):
        client.post(f"/api/v1/approvals/{approval['id']}/approve", json={})
    with SessionLocal() as db:
        assert db.get(Approval, approval["id"]).status == "PENDING"
        assert db.get(Creative, creative_id).status == "READY_FOR_REVIEW"
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action.in_(["APPROVAL_APPROVED", "CREATIVE_APPROVED"]))) == 0
        assert db.scalar(select(func.count()).select_from(Notification)) == 0


def test_decision_log_failure_rolls_back_approval_creative_and_notification(client, monkeypatch):
    _, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    from apps.api.app.services import creative_approval_decisions
    monkeypatch.setattr(creative_approval_decisions, "log_decision", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("log failure")))
    with pytest.raises(RuntimeError):
        client.post(f"/api/v1/approvals/{approval['id']}/approve", json={})
    with SessionLocal() as db:
        assert db.get(Approval, approval["id"]).status == "PENDING"
        assert db.get(Creative, creative_id).status == "READY_FOR_REVIEW"
        assert db.scalar(select(func.count()).select_from(Notification)) == 0


def test_creative_approval_snapshot_captures_source_and_editorial_context(client):
    _, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    with SessionLocal() as db:
        creative = db.get(Creative, creative_id)
        assert creative.creation_source == "CAMPAIGN_APPROVAL"
        assert creative.source_campaign_approval_id in approval["description"]
        assert creative.source_assessment_id in approval["description"]
        assert creative.generation_mode in approval["description"]
        assert creative.experiment_id is None or creative.experiment_id in approval["requestedPayload"]["experimentId"]
        assert approval["requestedPayload"]["campaignId"] == creative.campaign_id


def test_concurrent_same_approval_decision_emits_side_effects_once(client):
    _, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    barrier = Barrier(2)
    def run():
        with SessionLocal() as db:
            barrier.wait()
            return CreativeApprovalDecisionService(db).decide(approval["id"], "APPROVED").status
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: run(), range(2)))
    assert outcomes == ["APPROVED", "APPROVED"]
    with SessionLocal() as db:
        assert db.get(Creative, creative_id).status == "APPROVED"
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "APPROVAL_APPROVED")) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "CREATIVE_APPROVED")) == 1
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.type == "APPROVAL")) == 1


def test_concurrent_opposite_decisions_have_one_winner_and_consistent_pair(client):
    _, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    barrier = Barrier(2)
    def run(status):
        with SessionLocal() as db:
            barrier.wait()
            try:
                return CreativeApprovalDecisionService(db).decide(approval["id"], status).status
            except HTTPException as exc:
                return exc.detail["code"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, ["APPROVED", "REJECTED"]))
    assert sum(value in {"APPROVED", "REJECTED"} for value in outcomes) == 1
    assert sum(value == "APPROVAL_DECISION_CONFLICT" for value in outcomes) == 1
    with SessionLocal() as db:
        assert db.get(Approval, approval["id"]).status == db.get(Creative, creative_id).status
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.type == "APPROVAL")) == 1


def test_deciding_creative_has_no_render_or_publish_side_effects(client):
    _, creative_id = make_creative(client)
    approval = submit(client, creative_id).json()
    assert client.post(f"/api/v1/approvals/{approval['id']}/approve", json={}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Creative)) == 1
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.type == "CREATIVE")) == 1
        assert db.scalar(select(func.count()).select_from(CreativeScene).where(CreativeScene.creative_id == creative_id)) == 1
        assert db.scalar(select(func.count()).select_from(MediaJob).where(MediaJob.creative_id == creative_id)) == 0
        assert db.scalar(select(func.count()).select_from(PublicationExecution).where(PublicationExecution.creative_id == creative_id)) == 0
