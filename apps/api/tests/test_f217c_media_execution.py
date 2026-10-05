from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from apps.api.app.core.config import settings
from apps.api.app.db.models import Approval, Campaign, Creative, DecisionLog, MediaJob, PublicationExecution
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.media_execution import MediaExecutionService
from apps.api.app.services.media_pipeline import (
    FakeMediaValidator, FakeSceneRenderer, FakeTimelineComposer,
    FakeVoiceRenderer, PipelineError, recover_interrupted, run_pipeline,
)
from apps.api.app.services.operations import utcnow
from apps.api.tests.test_f217a_media_handoff import create, make_creative


def prepare(client, monkeypatch, *, scenes=1):
    monkeypatch.setattr(settings, "media_pipeline_mode", "FAKE")
    creative_id, campaign_id, campaign_approval_id, approval_id = make_creative(scenes=scenes)
    response = create(client, creative_id)
    assert response.status_code == 201
    return creative_id, campaign_id, campaign_approval_id, approval_id, response.json()


def actions(db, job_id, action):
    return db.scalar(select(func.count()).select_from(DecisionLog).where(
        DecisionLog.entity_id == job_id, DecisionLog.action == action)) or 0


def test_start_is_winner_only_replay_and_logs_real_mode(client, monkeypatch):
    creative_id, campaign_id, campaign_approval_id, creative_approval_id, job = prepare(client, monkeypatch)
    calls = []
    monkeypatch.setattr("apps.api.app.api.routes.run_media_background", lambda job_id: calls.append(job_id))
    started = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    replay = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert started.status_code == replay.status_code == 200
    assert started.json()["status"] == replay.json()["status"] == "PREPARING"
    assert len(calls) == 1 and calls == [job["id"]]
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"])
        assert row.progress_percent == 5 and row.current_stage == "PREPARING"
        assert row.started_at is not None and row.active_key is not None
        assert actions(db, job["id"], "MEDIA_JOB_STARTED") == 1
        assert actions(db, job["id"], "MEDIA_PREPARING") == 1
        started_log = db.scalar(select(DecisionLog).where(DecisionLog.entity_id == job["id"], DecisionLog.action == "MEDIA_JOB_STARTED"))
        assert started_log.metadata_["mode"] == "FAKE"
        assert started_log.metadata_["inputFingerprint"] == row.input_fingerprint
        assert db.scalar(select(func.count()).select_from(MediaJob)) == 1
        assert db.scalar(select(func.count()).select_from(PublicationExecution)) == 0
        assert db.get(Creative, creative_id).status == "APPROVED"
        assert db.get(Campaign, campaign_id).status == "APPROVED"
        assert db.get(Approval, creative_approval_id).status == db.get(Approval, campaign_approval_id).status == "APPROVED"


def test_unknown_job_returns_404_for_start_and_cancel(client):
    for action in ("start", "cancel"):
        response = client.post(f"/api/v1/media-jobs/missing-media-job/{action}")
        assert response.status_code == 404


@pytest.mark.parametrize("status", ["PREPARING", "RENDERING_AUDIO", "RENDERING_SCENES", "COMPOSING", "VALIDATING"])
def test_active_start_replay_is_idempotent_without_rescheduling(client, monkeypatch, status):
    _, _, _, _, job = prepare(client, monkeypatch)
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"])
        row.status = status; row.current_stage = status; row.started_at = utcnow(); row.progress_percent = 17
        db.commit(); started_at = row.started_at
    calls = []
    monkeypatch.setattr("apps.api.app.api.routes.run_media_background", lambda job_id: calls.append(job_id))
    response = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert response.status_code == 200 and response.json()["status"] == status
    assert calls == []
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"])
        assert row.started_at.replace(tzinfo=timezone.utc) == started_at.replace(tzinfo=timezone.utc) and row.progress_percent == 17
        assert actions(db, job["id"], "MEDIA_JOB_STARTED") == 0
        assert actions(db, job["id"], "MEDIA_PREPARING") == 0


@pytest.mark.parametrize("status", ["COMPLETED", "FAILED", "CANCELED"])
def test_terminal_start_is_structured_conflict(client, monkeypatch, status):
    _, _, _, _, job = prepare(client, monkeypatch)
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"]); row.status = status; row.active_key = None; db.commit()
    response = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MEDIA_JOB_NOT_STARTABLE"
    assert response.json()["detail"]["mediaJobStatus"] == status


def test_start_missing_context_and_stale_fingerprint_leave_queued(client, monkeypatch):
    creative_id, _, _, _, job = prepare(client, monkeypatch)
    with SessionLocal() as db:
        db.get(Creative, creative_id).hook = "Conteúdo alterado depois do preparo"; db.commit()
    response = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_JOB_INPUT_STALE"
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"])
        assert row.status == "QUEUED" and row.started_at is None and row.progress_percent == 0
        assert actions(db, job["id"], "MEDIA_JOB_STARTED") == 0


def test_start_campaign_readiness_change_is_invalidated_and_job_count_is_stable(client, monkeypatch):
    _, campaign_id, _, _, job = prepare(client, monkeypatch)
    with SessionLocal() as db:
        db.get(Campaign, campaign_id).primary_message = None; db.commit()
        count_before = db.scalar(select(func.count()).select_from(MediaJob))
    response = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_START_INVALIDATED"
    assert response.json()["detail"]["blockers"]
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"])
        assert row.status == "QUEUED" and row.started_at is None
        assert db.scalar(select(func.count()).select_from(MediaJob)) == count_before
        assert actions(db, row.id, "MEDIA_JOB_STARTED") == 0


def test_start_requires_the_only_active_job_to_be_the_requested_job(client, monkeypatch):
    creative_id, _, _, _, first = prepare(client, monkeypatch)
    with SessionLocal() as db:
        # Simulate damaged lifecycle data which bypassed the unique active key.
        db.get(MediaJob, first["id"]).active_key = None
        db.add(MediaJob(creative_id=creative_id, render_type="STANDARD", status="QUEUED", width=1080, height=1920,
                        creation_key="damaged-second-active-job", active_key=None, input_fingerprint=first["inputFingerprint"],
                        progress_percent=0, attempt_number=1))
        db.commit()
    response = client.post(f"/api/v1/media-jobs/{first['id']}/start")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_JOB_STATE_INCONSISTENT"
    with SessionLocal() as db:
        assert db.get(MediaJob, first["id"]).status == "QUEUED"
        assert db.scalar(select(func.count()).select_from(MediaJob).where(MediaJob.creative_id == creative_id, MediaJob.status == "QUEUED")) == 2


def test_start_invalidated_approval_or_readiness_is_blocked(client, monkeypatch):
    creative_id, _, _, approval_id, job = prepare(client, monkeypatch)
    with SessionLocal() as db:
        db.get(Approval, approval_id).status = "REJECTED"; db.commit()
    response = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_START_INVALIDATED"

    creative2, _, _, _, job2 = prepare(client, monkeypatch)
    with SessionLocal() as db:
        db.get(Creative, creative2).status = "DRAFT"; db.commit()
    response = client.post(f"/api/v1/media-jobs/{job2['id']}/start")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_START_INVALIDATED"
    with SessionLocal() as db:
        assert db.get(MediaJob, job2["id"]).status == "QUEUED"


def test_start_detects_missing_and_duplicate_source_approval(client, monkeypatch):
    _, _, _, approval_id, job = prepare(client, monkeypatch)
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"]); row.source_creative_approval_id = None
        db.get(Approval, approval_id).status = "REJECTED"; db.commit()
    response = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert response.status_code == 409 and response.json()["detail"]["code"] in {"MEDIA_START_INVALIDATED", "MEDIA_JOB_STATE_INCONSISTENT"}

    _, _, _, _, job2 = prepare(client, monkeypatch)
    with SessionLocal() as db:
        original = db.get(Approval, job2["sourceCreativeApprovalId"])
        db.add(Approval(type="CREATIVE", status="APPROVED", title="Duplicate", description="snapshot", entity_type="CREATIVE", entity_id=original.entity_id, requested_payload={}))
        db.commit()
    response = client.post(f"/api/v1/media-jobs/{job2['id']}/start")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_START_INVALIDATED"


def test_structured_preflight_failure_is_read_only_and_retryable(client, monkeypatch):
    _, _, _, _, job = prepare(client, monkeypatch)
    monkeypatch.setattr(settings, "media_pipeline_mode", "LOCAL")
    monkeypatch.setattr("apps.api.app.services.local_media.local_preflight_blockers", lambda db, row: [{"code": "FFMPEG_NOT_AVAILABLE", "message": "FFmpeg não está disponível."}])
    response = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_START_PREFLIGHT_FAILED"
    assert response.json()["detail"]["blockers"][0]["code"] == "FFMPEG_NOT_AVAILABLE"
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"])
        assert row.status == "QUEUED" and row.started_at is None and row.progress_percent == 0
        assert row.error_code is None and actions(db, row.id, "MEDIA_JOB_STARTED") == 0 and actions(db, row.id, "MEDIA_PREPARING") == 0
    monkeypatch.setattr("apps.api.app.services.local_media.local_preflight_blockers", lambda db, row: [])
    monkeypatch.setattr("apps.api.app.api.routes.run_media_background", lambda job_id: None)
    started = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert started.status_code == 200 and started.json()["status"] == "PREPARING"
    with SessionLocal() as db:
        log = db.scalar(select(DecisionLog).where(DecisionLog.entity_id == job["id"], DecisionLog.action == "MEDIA_JOB_STARTED"))
        assert log.metadata_["mode"] == "LOCAL"


def test_invalid_pipeline_mode_is_structured_and_non_mutating(client, monkeypatch):
    _, _, _, _, job = prepare(client, monkeypatch)
    monkeypatch.setattr(settings, "media_pipeline_mode", "SOMETHING_ELSE")
    response = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_PIPELINE_MODE_INVALID"
    with SessionLocal() as db:
        assert db.get(MediaJob, job["id"]).status == "QUEUED"


def test_cancel_is_idempotent_releases_gate_and_terminal_conflicts(client, monkeypatch):
    _, _, _, _, job = prepare(client, monkeypatch)
    first = client.post(f"/api/v1/media-jobs/{job['id']}/cancel")
    with SessionLocal() as db:
        completed_at = db.get(MediaJob, job["id"]).completed_at
    second = client.post(f"/api/v1/media-jobs/{job['id']}/cancel")
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "CANCELED"
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"])
        assert row.active_key is None and row.error_code == "JOB_CANCELED" and row.completed_at == completed_at
        assert row.started_at is None
        assert actions(db, row.id, "MEDIA_JOB_CANCELED") == 1
        assert db.scalar(select(func.count()).select_from(MediaJob)) == 1
        assert db.scalar(select(func.count()).select_from(PublicationExecution)) == 0
    for terminal in ("COMPLETED", "FAILED"):
        _, _, _, _, other = prepare(client, monkeypatch)
        with SessionLocal() as db:
            row = db.get(MediaJob, other["id"]); row.status = terminal; row.active_key = None; db.commit()
        response = client.post(f"/api/v1/media-jobs/{other['id']}/cancel")
        assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_JOB_ALREADY_TERMINAL"
        assert client.get(f"/api/v1/media-jobs/{other['id']}").json()["status"] == terminal


@pytest.mark.parametrize("status", ["QUEUED", "PREPARING", "RENDERING_AUDIO", "RENDERING_SCENES", "COMPOSING", "VALIDATING"])
def test_cancel_all_active_states(client, monkeypatch, status):
    _, _, _, _, job = prepare(client, monkeypatch)
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"]); row.status = status; row.current_stage = status; db.commit()
    response = client.post(f"/api/v1/media-jobs/{job['id']}/cancel")
    assert response.status_code == 200 and response.json()["status"] == "CANCELED"


def test_concurrent_start_has_one_cas_winner_and_one_start_log(client, monkeypatch):
    _, _, _, _, job = prepare(client, monkeypatch)
    barrier = Barrier(2)
    def start_once():
        with SessionLocal() as db:
            barrier.wait()
            try:
                return MediaExecutionService(db).start(job["id"]).started_now
            except HTTPException:
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: start_once(), range(2)))
    assert sum(results) == 1
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"])
        assert row.status == "PREPARING" and row.started_at is not None
        assert actions(db, row.id, "MEDIA_JOB_STARTED") == actions(db, row.id, "MEDIA_PREPARING") == 1
        assert db.scalar(select(func.count()).select_from(MediaJob)) == 1


def test_concurrent_http_start_schedules_background_once(client, monkeypatch):
    _, _, _, _, job = prepare(client, monkeypatch)
    calls = []
    monkeypatch.setattr("apps.api.app.api.routes.run_media_background", lambda job_id: calls.append(job_id))
    barrier = Barrier(2)
    def request_start(_):
        barrier.wait()
        return client.post(f"/api/v1/media-jobs/{job['id']}/start")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(request_start, range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert calls == [job["id"]]
    with SessionLocal() as db:
        assert actions(db, job["id"], "MEDIA_JOB_STARTED") == actions(db, job["id"], "MEDIA_PREPARING") == 1


def test_start_cancel_race_always_leaves_canceled_terminal(client, monkeypatch):
    _, _, _, _, job = prepare(client, monkeypatch)
    barrier = Barrier(2)
    def op(which):
        with SessionLocal() as db:
            barrier.wait()
            try:
                if which == "start":
                    return MediaExecutionService(db).start(job["id"]).started_now
                MediaExecutionService(db).cancel(job["id"]); return "canceled"
            except HTTPException:
                return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(op, ["start", "cancel"]))
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"])
        assert row.status == "CANCELED" and row.active_key is None
        assert actions(db, row.id, "MEDIA_JOB_CANCELED") == 1
        assert actions(db, row.id, "MEDIA_JOB_COMPLETED") == 0 and actions(db, row.id, "MEDIA_JOB_FAILED") == 0


def test_pipeline_checks_cancel_between_scenes_and_does_not_duplicate_cancel_log(client, monkeypatch):
    creative_id, _, _, _, job = prepare(client, monkeypatch, scenes=3)
    class CancelAfterFirstScene(FakeSceneRenderer):
        def __init__(self): super().__init__(); self.seen = []
        def render(self, spec, audio, width, height):
            self.seen.append(spec.order_index)
            if len(self.seen) == 1:
                with SessionLocal() as db: MediaExecutionService(db).cancel(job["id"])
            return super().render(spec, audio, width, height)
    renderer = CancelAfterFirstScene()
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"]); row.status = "PREPARING"; db.commit()
        run_pipeline(db, row.id, voice=FakeVoiceRenderer(), scene_renderer=renderer, composer=FakeTimelineComposer(), validator=FakeMediaValidator())
        db.refresh(row)
        assert row.status == "CANCELED" and row.active_key is None
        assert renderer.seen == [0]
        assert actions(db, row.id, "MEDIA_JOB_CANCELED") == 1
        assert actions(db, row.id, "MEDIA_JOB_COMPLETED") == actions(db, row.id, "MEDIA_JOB_FAILED") == 0


def test_pipeline_exception_after_cancel_and_cancel_before_completion_keep_canceled(client, monkeypatch):
    _, _, _, _, job = prepare(client, monkeypatch)
    class CancelThenFail:
        def render(self, spec):
            with SessionLocal() as db: MediaExecutionService(db).cancel(job["id"])
            raise RuntimeError("internal failure")
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"]); row.status = "PREPARING"; db.commit()
        run_pipeline(db, row.id, voice=CancelThenFail(), scene_renderer=FakeSceneRenderer(), composer=FakeTimelineComposer(), validator=FakeMediaValidator())
        db.refresh(row)
        assert row.status == "CANCELED" and actions(db, row.id, "MEDIA_JOB_CANCELED") == 1
        assert actions(db, row.id, "MEDIA_JOB_FAILED") == 0

    _, _, _, _, job2 = prepare(client, monkeypatch)
    class CancelInValidation(FakeMediaValidator):
        def validate(self, output):
            with SessionLocal() as db: MediaExecutionService(db).cancel(job2["id"])
            return super().validate(output)
    with SessionLocal() as db:
        row = db.get(MediaJob, job2["id"]); row.status = "PREPARING"; db.commit()
        run_pipeline(db, row.id, voice=FakeVoiceRenderer(), scene_renderer=FakeSceneRenderer(), composer=FakeTimelineComposer(), validator=CancelInValidation())
        db.refresh(row)
        assert row.status == "CANCELED"
        assert actions(db, row.id, "MEDIA_JOB_COMPLETED") == actions(db, row.id, "MEDIA_JOB_FAILED") == 0


@pytest.mark.parametrize("status", ["PREPARING", "RENDERING_AUDIO", "RENDERING_SCENES", "COMPOSING", "VALIDATING"])
def test_recovery_is_cas_idempotent_and_leaves_queued_and_terminal_unchanged(client, monkeypatch, status):
    _, _, _, _, active = prepare(client, monkeypatch)
    _, _, _, _, queued = prepare(client, monkeypatch)
    _, _, _, _, canceled = prepare(client, monkeypatch)
    with SessionLocal() as db:
        row = db.get(MediaJob, active["id"]); row.status = status
        db.get(MediaJob, canceled["id"]).status = "CANCELED"
        db.commit()
        assert recover_interrupted(db) == 1
        assert recover_interrupted(db) == 0
        assert row.status == "FAILED" and row.error_code == "JOB_INTERRUPTED" and row.active_key is None
        assert db.get(MediaJob, queued["id"]).status == "QUEUED"
        assert db.get(MediaJob, canceled["id"]).status == "CANCELED"
        assert actions(db, active["id"], "MEDIA_JOB_FAILED") == 1


def test_legacy_job_without_traceability_remains_startable(client, monkeypatch):
    monkeypatch.setattr(settings, "media_pipeline_mode", "FAKE")
    creative_id, *_ = make_creative(controlled=False)
    job = create(client, creative_id).json()
    with SessionLocal() as db:
        row = db.get(MediaJob, job["id"]); row.creation_source = None; row.source_creative_approval_id = None; db.commit()
    monkeypatch.setattr("apps.api.app.api.routes.run_media_background", lambda job_id: None)
    response = client.post(f"/api/v1/media-jobs/{job['id']}/start")
    assert response.status_code == 200 and response.json()["status"] == "PREPARING", response.json()
