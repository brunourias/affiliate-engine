"""Single-writer execution lifecycle for prepared media jobs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import Approval, Creative, MediaJob
from apps.api.app.services import creatives as creative_service
from apps.api.app.services.format_decision import CreativeFormatDecisionEngine
from apps.api.app.services.media_handoff import MediaHandoffService
from apps.api.app.services.media_pipeline import ACTIVE, TERMINAL
from apps.api.app.services.operations import log_decision


def _error(code: str, message: str, status: int = 409, **extra):
    return HTTPException(status, {"code": code, "message": message, **extra})


@dataclass(frozen=True)
class StartResult:
    job: MediaJob
    started_now: bool


class MediaExecutionService:
    def __init__(self, db: Session):
        self.db = db

    def _job(self, job_id: str) -> MediaJob:
        job = self.db.get(MediaJob, job_id)
        if not job:
            raise HTTPException(404, "Job de mídia não encontrado")
        return job

    @staticmethod
    def _terminal_error(job: MediaJob):
        return _error("MEDIA_JOB_NOT_STARTABLE", "Esta produção não está disponível para iniciar.",
                      mediaJobId=job.id, mediaJobStatus=job.status)

    def _validate_context(self, job: MediaJob) -> None:
        creative = self.db.get(Creative, job.creative_id)
        if not creative or creative.status != "APPROVED":
            raise _error("MEDIA_START_INVALIDATED", "O contexto atual do criativo não permite iniciar esta produção.",
                         blockers=[{"code": "CREATIVE_NOT_APPROVED", "message": "O criativo não está aprovado."}], warnings=[])

        handoff = MediaHandoffService(self.db)
        context, approval, expected_source = handoff._eligible_context(creative, job.render_type)
        if context["state"] != "READY_TO_CREATE":
            raise _error("MEDIA_START_INVALIDATED", "O contexto atual do criativo não permite iniciar esta produção.",
                         blockers=[{"code": context.get("reasonCode") or "MEDIA_CONTEXT_INVALID", "message": "O contexto de aprovação ou formato do criativo foi alterado."}], warnings=context.get("warnings") or [])

        source = job.creation_source
        if source == "CREATIVE_APPROVAL":
            if not approval or not job.source_creative_approval_id or approval.id != job.source_creative_approval_id:
                raise _error("MEDIA_JOB_STATE_INCONSISTENT", "A aprovação de origem desta produção não corresponde ao estado atual.")
        elif source == "LEGACY_APPROVED_CREATIVE":
            # Legacy jobs are accepted only when the Creative still has no tracked
            # approval. A newly tracked approval must not be silently ignored.
            if expected_source != "LEGACY_APPROVED_CREATIVE" or job.source_creative_approval_id is not None:
                raise _error("MEDIA_JOB_STATE_INCONSISTENT", "A origem desta produção não corresponde ao estado atual.")
        elif source is None:
            # Historical rows without traceability remain usable only when the
            # Creative is genuinely legacy and has no approval record.
            rows = list(self.db.scalars(select(Approval.id).where(
                Approval.type == "CREATIVE", Approval.entity_type == "CREATIVE", Approval.entity_id == creative.id)))
            if creative.creation_source is not None or rows or job.source_creative_approval_id is not None:
                raise _error("MEDIA_JOB_STATE_INCONSISTENT", "Não foi possível validar a origem desta produção.")
        else:
            raise _error("MEDIA_JOB_STATE_INCONSISTENT", "A origem desta produção não é reconhecida.")

        readiness = creative_service.readiness(self.db, creative)
        blockers = readiness.get("blockers") or []
        warnings = readiness.get("warnings") or []
        if blockers:
            raise _error("MEDIA_START_INVALIDATED", "O contexto atual do criativo não permite iniciar esta produção.",
                         blockers=blockers, warnings=warnings)

        active = handoff._active_jobs(creative.id)
        if (len(active) != 1 or active[0].id != job.id
                or job.active_key != f"MEDIA_ACTIVE:{creative.id}"):
            raise _error("MEDIA_JOB_STATE_INCONSISTENT", "A fila de produção deste criativo está inconsistente.",
                         mediaJobId=job.id)

        prepared = handoff._fingerprint(job)
        current = CreativeFormatDecisionEngine(self.db, lambda: {}).input_fingerprint(creative.id, "VIDEO_SHORT")
        if not prepared or prepared != current:
            raise _error("MEDIA_JOB_INPUT_STALE", "Os dados usados para preparar esta produção foram alterados.",
                         preparedFingerprint=prepared, currentFingerprint=current)

        if job.creation_source == "CREATIVE_APPROVAL" and job.source_creative_approval_id != context.get("creativeApprovalId"):
            raise _error("MEDIA_JOB_STATE_INCONSISTENT", "A aprovação de origem desta produção não corresponde ao estado atual.")

    def _preflight(self, job: MediaJob, mode: str) -> None:
        if mode == "LOCAL":
            from apps.api.app.services.local_media import local_preflight_blockers
            blockers = local_preflight_blockers(self.db, job)
            if blockers:
                raise _error("MEDIA_START_PREFLIGHT_FAILED", "Não foi possível iniciar a produção.", blockers=blockers)

    def start(self, job_id: str) -> StartResult:
        job = self._job(job_id)
        if job.status in ACTIVE:
            return StartResult(job, False)
        if job.status in TERMINAL:
            raise self._terminal_error(job)
        if job.status != "QUEUED":
            raise _error("MEDIA_JOB_NOT_STARTABLE", "Esta produção não está disponível para iniciar.",
                         mediaJobId=job.id, mediaJobStatus=job.status)

        self._validate_context(job)
        mode = str(settings.media_pipeline_mode or "").upper()
        if mode not in {"LOCAL", "FAKE"}:
            raise _error("MEDIA_PIPELINE_MODE_INVALID", "O modo de produção de mídia não está configurado.")
        self._preflight(job, mode)

        now = datetime.now(timezone.utc)
        try:
            changed = self.db.execute(update(MediaJob).where(
                MediaJob.id == job.id, MediaJob.status == "QUEUED"
            ).values(status="PREPARING", current_stage="PREPARING", progress_percent=5, started_at=now)).rowcount
            if changed != 1:
                self.db.rollback()
                current = self._job(job_id)
                if current.status in ACTIVE:
                    return StartResult(current, False)
                if current.status in TERMINAL:
                    raise self._terminal_error(current)
                raise _error("MEDIA_JOB_STATE_INCONSISTENT", "A produção mudou durante a solicitação de início.",
                             mediaJobId=current.id, mediaJobStatus=current.status)

            metadata = {
                "creativeId": job.creative_id, "renderType": job.render_type,
                "attemptNumber": job.attempt_number, "inputFingerprint": job.input_fingerprint,
                "mode": mode, "sourceCreativeApprovalId": job.source_creative_approval_id,
                "creationSource": job.creation_source,
            }
            log_decision(self.db, "OPERATOR", "MEDIA_JOB", "MEDIA_JOB_STARTED", job.id, metadata=metadata)
            log_decision(self.db, "SYSTEM", "MEDIA_JOB", "MEDIA_PREPARING", job.id, metadata={"progress": 5})
            self.db.commit()
            started = self.db.get(MediaJob, job.id)
            return StartResult(started, True)
        except OperationalError:
            self.db.rollback()
            current = self._job(job_id)
            if current.status in ACTIVE:
                return StartResult(current, False)
            if current.status in TERMINAL:
                raise self._terminal_error(current)
            raise _error("MEDIA_JOB_STATE_INCONSISTENT", "A produção mudou durante a solicitação de início.",
                         mediaJobId=current.id, mediaJobStatus=current.status)

    def cancel(self, job_id: str) -> MediaJob:
        self._job(job_id)
        cancelable = {"QUEUED", *ACTIVE}
        for _ in range(3):
            now = datetime.now(timezone.utc)
            try:
                changed = self.db.execute(update(MediaJob).where(
                    MediaJob.id == job_id, MediaJob.status.in_(cancelable)
                ).values(status="CANCELED", current_stage="CANCELED", active_key=None,
                         error_code="JOB_CANCELED", error_message="Renderização cancelada pelo operador.", completed_at=now)).rowcount
                if changed == 1:
                    log_decision(self.db, "OPERATOR", "MEDIA_JOB", "MEDIA_JOB_CANCELED", job_id)
                    self.db.commit()
                    return self._job(job_id)
                self.db.rollback()
                current = self._job(job_id)
                if current.status == "CANCELED":
                    return current
                if current.status in TERMINAL:
                    raise _error("MEDIA_JOB_ALREADY_TERMINAL", "Esta produção já foi finalizada.",
                                 mediaJobId=current.id, mediaJobStatus=current.status)
            except OperationalError:
                self.db.rollback()
                current = self._job(job_id)
                if current.status == "CANCELED":
                    return current
                if current.status in TERMINAL:
                    raise _error("MEDIA_JOB_ALREADY_TERMINAL", "Esta produção já foi finalizada.",
                                 mediaJobId=current.id, mediaJobStatus=current.status)
        current = self._job(job_id)
        if current.status == "CANCELED":
            return current
        if current.status in TERMINAL:
            raise _error("MEDIA_JOB_ALREADY_TERMINAL", "Esta produção já foi finalizada.",
                         mediaJobId=current.id, mediaJobStatus=current.status)
        raise _error("MEDIA_JOB_STATE_INCONSISTENT", "Não foi possível cancelar a produção com segurança.",
                     mediaJobId=current.id, mediaJobStatus=current.status)
