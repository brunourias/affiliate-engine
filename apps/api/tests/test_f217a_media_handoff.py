from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from sqlalchemy import func, select

from apps.api.app.core.config import settings
from apps.api.app.db.models import (
    Approval, Campaign, CampaignAngle, CampaignChannel, CampaignExperiment,
    Creative, CreativeScene, CuratorAssessment, CuratorCandidate,
    DecisionLog, MediaAsset, MediaJob, PublicationExecution,
)
from apps.api.app.db.session import SessionLocal
from apps.api.app.services import format_decision
from apps.api.app.services.media_pipeline import (
    FakeMediaValidator, FakeSceneRenderer, FakeTimelineComposer,
    FakeVoiceRenderer, recover_interrupted, run_pipeline,
)
from apps.api.app.services.media_execution import MediaExecutionService


def make_creative(status="APPROVED", *, controlled=True, content_type="SHORT_VIDEO", scenes=1):
    with SessionLocal() as db:
        candidate = CuratorCandidate(provider="OTHER", source_type="MANUAL", entity_type="MANUAL")
        db.add(candidate)
        db.flush()
        assessment = CuratorAssessment(
            candidate_id=candidate.id, assessment_version=1,
            evidence_status="SUFFICIENT_EVIDENCE", evidence_level="DATA_ANALYZED",
            trust_gate="PASS", trust_reasons=[], trust_warnings=[],
            recommendation_score=80, recommendation_coverage_percent=100,
            recommendation_label="GOOD", opportunity_score=70,
            opportunity_coverage_percent=100, price_verdict="FAIR_PRICE",
            editorial_verdict="WORTH_IT", recommendation_pillars={},
            opportunity_pillars={}, evidence_ids_used=[], unknown_fields=[], rationale={},
        )
        db.add(assessment)
        db.flush()
        campaign = Campaign(
            candidate_id=candidate.id, assessment_id=assessment.id, name="Produto",
            status="APPROVED", objective="EDUCATION", editorial_verdict_snapshot="WORTH_IT",
            trust_gate_snapshot="PASS", recommendation_score_snapshot=80,
            opportunity_score_snapshot=70, price_verdict_snapshot="FAIR_PRICE",
            campaign_priority="HIGH", target_audience="Pessoas interessadas",
            editorial_positioning="Compra consciente", primary_message="Compare antes de escolher",
            affiliate_url="https://example.test/oferta", affiliate_url_verified_at=assessment.created_at,
            disclosure_text="Aviso de afiliação", cta_strategy="Confira os detalhes",
            trust_warnings_snapshot=[], required_disclosures=[], required_warnings=[], forbidden_claims=[],
        )
        db.add(campaign)
        db.flush()
        campaign_approval = Approval(
            type="CAMPAIGN", status="APPROVED", title="Aprovar campanha", description="snapshot",
            entity_type="CAMPAIGN", entity_id=campaign.id, requested_payload={}, decided_at=datetime.now(timezone.utc),
        )
        db.add(campaign_approval)
        angle = CampaignAngle(campaign_id=campaign.id, angle_type="HOME_USE", title="Uso doméstico", premise="Uso doméstico", status="ACTIVE")
        db.add(angle)
        db.flush()
        db.add(CampaignChannel(campaign_id=campaign.id, channel="GENERIC", enabled=True))
        db.add(CampaignExperiment(campaign_id=campaign.id, angle_id=angle.id, hypothesis="Teste editorial", status="PLANNED"))
        row = Creative(
            campaign_id=campaign.id, name="Criativo teste", status=status,
            content_type=content_type, target_channel="GENERIC", objective_snapshot="EDUCATION",
            editorial_verdict_snapshot="WORTH_IT", price_verdict_snapshot="FAIR_PRICE",
            hook="Hook de teste", body_script="Roteiro de teste", cta="Confira os detalhes",
            estimated_duration_seconds=20, disclosure_text="Aviso de afiliação",
            required_warnings=[], forbidden_claims=[],
            creation_source="CAMPAIGN_APPROVAL" if controlled else None,
            source_campaign_approval_id=campaign_approval.id if controlled else None,
            source_assessment_id=assessment.id if controlled else None,
        )
        db.add(row)
        db.flush()
        for index in range(scenes):
            db.add(CreativeScene(
                creative_id=row.id, order_index=index, scene_type="PRODUCT", speaker="NARRATOR",
                purpose="BENEFIT", narration_text="Uma frase curta para teste", duration_seconds=3,
                required_warning_codes=[],
            ))
        creative_approval = None
        if controlled:
            creative_approval = Approval(
                type="CREATIVE", status="APPROVED", title="Aprovar criativo", description="snapshot",
                entity_type="CREATIVE", entity_id=row.id, requested_payload={}, decided_at=datetime.now(timezone.utc),
            )
            db.add(creative_approval)
        db.commit()
        return row.id, campaign.id, campaign_approval.id, creative_approval.id if creative_approval else None


def create(client, creative_id, render_type="PREVIEW"):
    return client.post(f"/api/v1/media-jobs/from-creative/{creative_id}", json={"renderType": render_type})


@pytest.mark.parametrize("status", ["DRAFT", "READY_FOR_REVIEW", "REJECTED", "ARCHIVED"])
def test_non_approved_creatives_cannot_prepare_media_job(client, status):
    creative_id, *_ = make_creative(status)
    response = create(client, creative_id)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CREATIVE_NOT_APPROVED"


def test_controlled_approved_and_legacy_approved_creatives_are_supported(client):
    controlled_id, *_ = make_creative()
    legacy_id, *_ = make_creative(controlled=False)
    controlled = client.get(f"/api/v1/creatives/{controlled_id}/media-handoff").json()
    legacy = client.get(f"/api/v1/creatives/{legacy_id}/media-handoff").json()
    assert controlled["state"] == "READY_TO_CREATE" and controlled["creativeApprovalId"]
    assert legacy["state"] == "READY_TO_CREATE" and legacy["creativeApprovalId"] is None
    assert "LEGACY_CREATIVE_APPROVAL_UNTRACKED" in {warning["code"] for warning in legacy["warnings"]}


def test_controlled_creative_requires_exactly_one_approved_creative_approval(client):
    creative_id, *_ = make_creative()
    with SessionLocal() as db:
        row = db.get(Creative, creative_id)
        db.add(Approval(type="CREATIVE", status="REJECTED", title="Histórica rejeitada", description="snapshot", entity_type="CREATIVE", entity_id=row.id, requested_payload={}))
        db.commit()
    assert client.get(f"/api/v1/creatives/{creative_id}/media-handoff").json()["state"] == "READY_TO_CREATE"
    with SessionLocal() as db:
        db.add(Approval(type="CREATIVE", status="APPROVED", title="Duplicada", description="snapshot", entity_type="CREATIVE", entity_id=creative_id, requested_payload={}))
        db.commit()
    state = client.get(f"/api/v1/creatives/{creative_id}/media-handoff").json()
    assert state["state"] == "NOT_ELIGIBLE" and state["reasonCode"] == "CREATIVE_APPROVAL_STATE_INCONSISTENT"


def test_missing_controlled_approval_blocks_handoff(client):
    creative_id, *_ = make_creative()
    with SessionLocal() as db:
        db.execute(select(Approval).where(Approval.entity_id == creative_id))
        row = db.scalar(select(Approval).where(Approval.type == "CREATIVE", Approval.entity_id == creative_id))
        db.delete(row)
        db.commit()
    response = create(client, creative_id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "CREATIVE_APPROVAL_REQUIRED"


@pytest.mark.parametrize("content_type", ["STATIC_POST", "STATIC_CARD", "CAROUSEL"])
def test_non_video_creative_formats_are_not_eligible(client, content_type):
    creative_id, *_ = make_creative(content_type=content_type)
    response = create(client, creative_id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "VIDEO_RENDER_NOT_ELIGIBLE"


def test_readiness_blockers_invalidate_new_handoff_without_regrading_approved_creative(client):
    creative_id, campaign_id, *_ = make_creative()
    with SessionLocal() as db:
        db.get(Campaign, campaign_id).primary_message = None
        db.commit()
    state = client.get(f"/api/v1/creatives/{creative_id}/media-handoff").json()
    response = create(client, creative_id)
    with SessionLocal() as db:
        assert db.get(Creative, creative_id).status == "APPROVED"
    assert state["state"] == "NOT_ELIGIBLE" and state["reasonCode"] == "MEDIA_HANDOFF_INVALIDATED"
    invalidated = next(item for item in state["blockers"] if item["code"] == "CAMPAIGN_CONTEXT_INVALIDATED")
    assert any(item["code"] == "PRIMARY_MESSAGE_REQUIRED" for item in invalidated["parentBlockers"])
    assert response.status_code == 409 and response.json()["detail"]["blockers"]


@pytest.mark.parametrize("render_type,size", [("PREVIEW", (540, 960)), ("STANDARD", (1080, 1920))])
def test_get_is_read_only_and_create_returns_queued_job_without_render_side_effects(client, render_type, size, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    creative_id, campaign_id, campaign_approval_id, creative_approval_id = make_creative()
    with SessionLocal() as db:
        before = {
            model.__tablename__: db.scalar(select(func.count()).select_from(model))
            for model in (MediaJob, DecisionLog, Approval, MediaAsset, PublicationExecution, CreativeScene)
        }
        scene = db.scalar(select(CreativeScene).where(CreativeScene.creative_id == creative_id))
        creative_row = db.get(Creative, creative_id)
        creative_updated = creative_row.updated_at
        approval_status = db.get(Approval, creative_approval_id).status
        fingerprint = format_decision.CreativeFormatDecisionEngine(db, lambda: {}).input_fingerprint(creative_id, "VIDEO_SHORT")
    state = client.get(f"/api/v1/creatives/{creative_id}/media-handoff?renderType={render_type}")
    assert state.status_code == 200 and state.json()["state"] == "READY_TO_CREATE"
    with SessionLocal() as db:
        after = {model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in (MediaJob, DecisionLog, Approval, MediaAsset, PublicationExecution, CreativeScene)}
        assert after == before
        assert db.get(Creative, creative_id).updated_at == creative_updated
        assert db.get(Approval, creative_approval_id).status == approval_status
        assert db.get(CreativeScene, scene.id)

    response = create(client, creative_id, render_type)
    assert response.status_code == 201
    job = response.json()
    assert (job["width"], job["height"], job["fps"], job["videoCodec"], job["audioCodec"]) == (*size, 30, "h264", "aac")
    assert job["status"] == "QUEUED" and job["startedAt"] is None and job["completedAt"] is None and job["progressPercent"] == 0
    assert job["inputFingerprint"] == fingerprint == job["validationDetails"]["inputFingerprint"]
    assert job["sourceCreativeApprovalId"] == creative_approval_id and job["creationSource"] == "CREATIVE_APPROVAL"
    assert job["attemptNumber"] == 1 and job["previousMediaJobId"] is None and job["creationKey"]
    assert "activeKey" not in job
    with SessionLocal() as db:
        created_logs = list(db.scalars(select(DecisionLog).where(DecisionLog.entity_id == job["id"], DecisionLog.action == "MEDIA_JOB_CREATED")))
        assert len(created_logs) == 1
        assert created_logs[0].metadata_["creativeApprovalId"] == creative_approval_id
        assert created_logs[0].metadata_["campaignId"] == campaign_id
        assert created_logs[0].metadata_["creationSource"] == "CREATIVE_APPROVAL"
        assert db.get(Creative, creative_id).status == "APPROVED"
        assert db.get(Approval, creative_approval_id).status == "APPROVED"
        assert db.scalar(select(func.count()).select_from(PublicationExecution)) == before["publication_executions"]
        assert db.scalar(select(func.count()).select_from(MediaAsset)) == before["media_assets"]
        actions = set(db.scalars(select(DecisionLog.action).where(DecisionLog.entity_id == job["id"])))
        assert not actions.intersection({"MEDIA_JOB_STARTED", "MEDIA_PREPARING", "MEDIA_AUDIO_RENDERED", "MEDIA_SCENE_RENDERED"})
    assert list(tmp_path.iterdir()) == []


def test_replay_returns_same_queued_job_without_second_log(client):
    creative_id, *_ = make_creative()
    first = create(client, creative_id).json()
    second = create(client, creative_id).json()
    assert first["id"] == second["id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MediaJob).where(MediaJob.creative_id == creative_id)) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.entity_id == first["id"], DecisionLog.action == "MEDIA_JOB_CREATED")) == 1
    assert client.get(f"/api/v1/creatives/{creative_id}/media-handoff").json()["state"] == "JOB_EXISTS"


def test_different_render_type_conflicts_with_existing_active_job(client):
    creative_id, *_ = make_creative()
    job = create(client, creative_id, "PREVIEW").json()
    state = client.get(f"/api/v1/creatives/{creative_id}/media-handoff?renderType=STANDARD").json()
    response = create(client, creative_id, "STANDARD")
    assert state["state"] == "ACTIVE_JOB_CONFLICT" and state["reasonCode"] == "MEDIA_JOB_ALREADY_ACTIVE"
    assert state["mediaJobId"] == job["id"] and state["mediaJobStatus"] == "QUEUED"
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_JOB_ALREADY_ACTIVE"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MediaJob).where(MediaJob.creative_id == creative_id)) == 1


def test_multiple_historical_active_jobs_are_reported_without_creating_another(client):
    creative_id, *_ = make_creative()
    first = create(client, creative_id).json()
    with SessionLocal() as db:
        original = db.get(MediaJob, first["id"])
        db.add(MediaJob(creative_id=creative_id, render_type="STANDARD", status="QUEUED", width=1080, height=1920, fps=30, video_codec="h264", audio_codec="aac", progress_percent=0, input_fingerprint="historical"))
        original.active_key = None
        db.commit()
    state = client.get(f"/api/v1/creatives/{creative_id}/media-handoff").json()
    response = create(client, creative_id)
    assert state["state"] == "MULTIPLE_ACTIVE_JOBS" and state["reasonCode"] == "MEDIA_JOB_STATE_INCONSISTENT"
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_JOB_STATE_INCONSISTENT"


def test_concurrent_same_request_converges_to_one_job(client, monkeypatch):
    creative_id, *_ = make_creative()
    barrier = Barrier(2)
    original = format_decision.CreativeFormatDecisionEngine.input_fingerprint
    def synchronized(self, creative_id, creative_format):
        result = original(self, creative_id, creative_format)
        barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(format_decision.CreativeFormatDecisionEngine, "input_fingerprint", synchronized)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: create(client, creative_id), range(2)))
    assert all(response.status_code == 201 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MediaJob).where(MediaJob.creative_id == creative_id)) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.entity_id == responses[0].json()["id"], DecisionLog.action == "MEDIA_JOB_CREATED")) == 1


def test_concurrent_preview_and_standard_allow_only_one_active_job(client, monkeypatch):
    creative_id, *_ = make_creative()
    barrier = Barrier(2)
    original = format_decision.CreativeFormatDecisionEngine.input_fingerprint
    def synchronized(self, creative_id, creative_format):
        result = original(self, creative_id, creative_format)
        barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(format_decision.CreativeFormatDecisionEngine, "input_fingerprint", synchronized)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda render: create(client, creative_id, render), ("PREVIEW", "STANDARD")))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert responses[[response.status_code for response in responses].index(409)].json()["detail"]["code"] == "MEDIA_JOB_ALREADY_ACTIVE"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MediaJob).where(MediaJob.creative_id == creative_id, MediaJob.status == "QUEUED")) == 1


def test_cancel_failure_completion_and_recovery_release_active_key(client):
    cancel_creative, *_ = make_creative()
    canceled = create(client, cancel_creative).json()
    assert client.post(f"/api/v1/media-jobs/{canceled['id']}/cancel").json()["status"] == "CANCELED"
    with SessionLocal() as db:
        assert db.get(MediaJob, canceled["id"]).active_key is None
    assert create(client, cancel_creative).json()["attemptNumber"] == 2

    failed_creative, *_ = make_creative()
    failed = create(client, failed_creative).json()
    with SessionLocal() as db:
        row = db.get(MediaJob, failed["id"]); row.status = "PREPARING"; db.commit()
        run_pipeline(db, row.id, voice=FakeVoiceRenderer(fail=True), scene_renderer=FakeSceneRenderer(), composer=FakeTimelineComposer(), validator=FakeMediaValidator())
        assert row.status == "FAILED" and row.active_key is None

    completed_creative, *_ = make_creative()
    completed = create(client, completed_creative).json()
    with SessionLocal() as db:
        row = db.get(MediaJob, completed["id"]); row.status = "PREPARING"; db.commit()
        run_pipeline(db, row.id, voice=FakeVoiceRenderer(), scene_renderer=FakeSceneRenderer(), composer=FakeTimelineComposer(), validator=FakeMediaValidator())
        assert row.status == "COMPLETED" and row.active_key is None

    unexpected_creative, *_ = make_creative()
    unexpected = create(client, unexpected_creative).json()
    class UnexpectedComposer:
        def compose(self, *args):
            raise RuntimeError("internal detail must not escape")
    with SessionLocal() as db:
        row = db.get(MediaJob, unexpected["id"]); row.status = "PREPARING"; db.commit()
        run_pipeline(db, row.id, voice=FakeVoiceRenderer(), scene_renderer=FakeSceneRenderer(), composer=UnexpectedComposer(), validator=FakeMediaValidator())
        assert row.status == "FAILED" and row.active_key is None and row.error_code == "PIPELINE_NOT_AVAILABLE"

    detected_cancel_creative, *_ = make_creative()
    detected_cancel = create(client, detected_cancel_creative).json()
    class CancelDuringVoice:
        def render(self, spec):
            with SessionLocal() as cancellation_db:
                MediaExecutionService(cancellation_db).cancel(detected_cancel["id"])
            return FakeVoiceRenderer().render(spec)
    with SessionLocal() as db:
        row = db.get(MediaJob, detected_cancel["id"]); row.status = "PREPARING"; db.commit()
        run_pipeline(db, row.id, voice=CancelDuringVoice(), scene_renderer=FakeSceneRenderer(), composer=FakeTimelineComposer(), validator=FakeMediaValidator())
        assert row.status == "CANCELED" and row.active_key is None

    interrupted_creative, *_ = make_creative()
    interrupted = create(client, interrupted_creative).json()
    with SessionLocal() as db:
        row = db.get(MediaJob, interrupted["id"]); row.status = "COMPOSING"; db.commit()
        assert recover_interrupted(db) == 1
        assert row.status == "FAILED" and row.error_code == "JOB_INTERRUPTED" and row.active_key is None


def test_terminal_retry_links_previous_job_and_new_fingerprint_resets_chain(client):
    creative_id, *_ = make_creative()
    first = create(client, creative_id).json()
    with SessionLocal() as db:
        row = db.get(MediaJob, first["id"]); row.status = "FAILED"; row.active_key = None; row.completed_at = datetime.now(timezone.utc); row.input_fingerprint = None; db.commit()
    second = create(client, creative_id).json()
    assert second["attemptNumber"] == 2 and second["previousMediaJobId"] == first["id"]
    with SessionLocal() as db:
        db.get(MediaJob, second["id"]).status = "FAILED"
        db.get(MediaJob, second["id"]).active_key = None
        db.get(Creative, creative_id).hook = "Hook atualizado"
        db.commit()
    third = create(client, creative_id).json()
    assert third["attemptNumber"] == 1 and third["previousMediaJobId"] is None

