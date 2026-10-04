"""Controlled, idempotent handoff from an approved Creative to a queued MediaJob.

This service intentionally does not start the media pipeline. Rendering remains
an explicit, separate operation handled by the existing start endpoint.
"""
from __future__ import annotations

import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from apps.api.app.db.models import Approval, Creative, MediaJob
from apps.api.app.services import creatives as creative_service
from apps.api.app.services.format_decision import CreativeFormatDecisionEngine
from apps.api.app.services.operations import log_decision
from apps.api.app.services.media_pipeline import ACTIVE, TERMINAL

RENDER_PROFILES = {"PREVIEW": (540, 960), "STANDARD": (1080, 1920)}
ACTIVE_STATUSES = {"QUEUED", *ACTIVE}


def _error(code: str, message: str, status: int = 409, **extra):
    return HTTPException(status, {"code": code, "message": message, **extra})


class MediaHandoffService:
    def __init__(self, db: Session):
        self.db = db

    def _creative(self, creative_id: str) -> Creative:
        creative = self.db.get(Creative, creative_id)
        if not creative:
            raise HTTPException(404, "Criativo não encontrado")
        return creative

    def _approval(self, creative: Creative) -> tuple[Approval | None, str | None]:
        rows = list(self.db.scalars(select(Approval).where(
            Approval.type == "CREATIVE",
            Approval.entity_type == "CREATIVE",
            Approval.entity_id == creative.id,
        ).order_by(Approval.created_at, Approval.id)))
        # A null origin with no Approval rows identifies legacy creatives.
        # If an Approval exists, even on a row whose origin predates tracking,
        # use the explicit lifecycle and require exactly one approved winner.
        if creative.creation_source is None and not rows:
            return None, None
        rows = [row for row in rows if row.status == "APPROVED"]
        if not rows:
            return None, "CREATIVE_APPROVAL_REQUIRED"
        if len(rows) != 1:
            return None, "CREATIVE_APPROVAL_STATE_INCONSISTENT"
        return rows[0], None

    def _base(self, creative: Creative, render_type: str) -> dict:
        return {
            "state": "NOT_ELIGIBLE", "creativeId": creative.id,
            "creativeStatus": creative.status, "renderType": render_type,
            "creativeApprovalId": None, "inputFingerprint": None,
            "mediaJobId": None, "mediaJobStatus": None,
            "attemptNumber": None, "previousMediaJobId": None,
            "reasonCode": None, "blockers": [], "warnings": [],
        }

    def _eligible_context(self, creative: Creative, render_type: str):
        result = self._base(creative, render_type)
        if creative.status != "APPROVED":
            return {**result, "reasonCode": "CREATIVE_NOT_APPROVED"}, None, None
        if render_type not in RENDER_PROFILES or creative.content_type not in {"SHORT_VIDEO", "VIDEO_SHORT"}:
            return {**result, "reasonCode": "VIDEO_RENDER_NOT_ELIGIBLE"}, None, None

        approval, approval_error = self._approval(creative)
        if approval_error:
            return {**result, "reasonCode": approval_error}, None, None
        warnings = []
        if creative.creation_source is None:
            warnings.append({"code": "LEGACY_CREATIVE_APPROVAL_UNTRACKED", "message": "A aprovação deste criativo não está vinculada ao fluxo atual."})

        fingerprint = CreativeFormatDecisionEngine(self.db, lambda: {}).input_fingerprint(creative.id, "VIDEO_SHORT")
        creation_source = "CREATIVE_APPROVAL" if approval else "LEGACY_APPROVED_CREATIVE"
        return {**result, "state": "READY_TO_CREATE", "creativeApprovalId": approval.id if approval else None,
                "inputFingerprint": fingerprint, "warnings": warnings}, approval, creation_source

    def _active_jobs(self, creative_id: str) -> list[MediaJob]:
        return list(self.db.scalars(select(MediaJob).where(
            MediaJob.creative_id == creative_id,
            MediaJob.status.in_(ACTIVE_STATUSES),
        ).order_by(MediaJob.created_at, MediaJob.id)))

    @staticmethod
    def _fingerprint(job: MediaJob) -> str | None:
        return job.input_fingerprint or (job.validation_details or {}).get("inputFingerprint")

    def _history(self, creative_id: str, render_type: str, fingerprint: str) -> tuple[int, str | None]:
        rows = self.db.scalars(select(MediaJob).where(
            MediaJob.creative_id == creative_id,
            MediaJob.render_type == render_type,
            MediaJob.status.in_(TERMINAL),
        ).order_by(MediaJob.created_at.desc(), MediaJob.id.desc()))
        previous = next((job for job in rows if self._fingerprint(job) == fingerprint), None)
        return (previous.attempt_number + 1, previous.id) if previous else (1, None)

    def state(self, creative_id: str, render_type: str = "PREVIEW") -> dict:
        creative = self._creative(creative_id)
        if render_type not in RENDER_PROFILES:
            raise HTTPException(422, "Perfil de vídeo inválido")
        base, approval, creation_source = self._eligible_context(creative, render_type)
        if base["state"] == "NOT_ELIGIBLE":
            return base

        active = self._active_jobs(creative.id)
        if len(active) > 1:
            return {**base, "state": "MULTIPLE_ACTIVE_JOBS", "reasonCode": "MEDIA_JOB_STATE_INCONSISTENT"}
        if active:
            job = active[0]
            same_request = job.render_type == render_type and self._fingerprint(job) == base["inputFingerprint"]
            return {**base, "state": "JOB_EXISTS" if same_request else "ACTIVE_JOB_CONFLICT",
                    "mediaJobId": job.id, "mediaJobStatus": job.status,
                    "attemptNumber": job.attempt_number, "previousMediaJobId": job.previous_media_job_id,
                    "reasonCode": None if same_request else "MEDIA_JOB_ALREADY_ACTIVE"}

        current_readiness = creative_service.readiness(self.db, creative)
        blockers = current_readiness.get("blockers") or []
        warnings = [*(base.get("warnings") or []), *(current_readiness.get("warnings") or [])]
        if blockers:
            return {**base, "state": "NOT_ELIGIBLE", "reasonCode": "MEDIA_HANDOFF_INVALIDATED",
                    "blockers": blockers, "warnings": warnings}

        attempt_number, previous_id = self._history(creative.id, render_type, base["inputFingerprint"])
        return {**base, "state": "READY_TO_CREATE", "warnings": warnings, "attemptNumber": attempt_number,
                "previousMediaJobId": previous_id}

    def _conflict_after_race(self, creative_id: str, render_type: str, fingerprint: str):
        # A uniqueness conflict is the cross-request arbiter. Re-read after
        # rollback so callers converge on the winner without a DB-specific lock.
        for _ in range(6):
            try:
                active = self._active_jobs(creative_id)
            except OperationalError:
                self.db.rollback()
                time.sleep(0.02)
                continue
            if len(active) > 1:
                raise _error("MEDIA_JOB_STATE_INCONSISTENT", "Há mais de uma produção ativa para este criativo.")
            if active:
                winner = active[0]
                if winner.render_type == render_type and self._fingerprint(winner) == fingerprint:
                    return winner
                raise _error("MEDIA_JOB_ALREADY_ACTIVE", "Já existe uma produção ativa diferente para este criativo.")
            time.sleep(0.02)
        raise _error("MEDIA_HANDOFF_CONFLICT", "A preparação de mídia está em andamento. Atualize o estado e tente novamente.")

    def create(self, creative_id: str, render_type: str = "PREVIEW") -> MediaJob:
        creative = self._creative(creative_id)
        if render_type not in RENDER_PROFILES:
            raise HTTPException(422, "Perfil de vídeo inválido")
        state = self.state(creative_id, render_type)
        if state["state"] == "JOB_EXISTS":
            return self.db.get(MediaJob, state["mediaJobId"])
        if state["state"] == "ACTIVE_JOB_CONFLICT":
            raise _error("MEDIA_JOB_ALREADY_ACTIVE", "Já existe uma produção ativa diferente para este criativo.", mediaJobId=state["mediaJobId"], mediaJobStatus=state["mediaJobStatus"])
        if state["state"] == "MULTIPLE_ACTIVE_JOBS":
            raise _error("MEDIA_JOB_STATE_INCONSISTENT", "Há mais de uma produção ativa para este criativo.")
        if state["state"] == "NOT_ELIGIBLE":
            code = state["reasonCode"] or "CREATIVE_NOT_APPROVED"
            messages = {
                "CREATIVE_NOT_APPROVED": "Somente criativos aprovados podem preparar uma produção de vídeo.",
                "VIDEO_RENDER_NOT_ELIGIBLE": "Este formato de criativo não é elegível para produção de vídeo.",
                "CREATIVE_APPROVAL_REQUIRED": "A aprovação do criativo é necessária para preparar a produção.",
                "CREATIVE_APPROVAL_STATE_INCONSISTENT": "O histórico de aprovações do criativo precisa ser revisado.",
                "MEDIA_HANDOFF_INVALIDATED": "O contexto atual do criativo não permite preparar uma nova produção.",
            }
            raise _error(code, messages.get(code, "Não foi possível preparar a produção do criativo."), blockers=state["blockers"], warnings=state["warnings"])

        fingerprint = state["inputFingerprint"]
        attempt_number = state["attemptNumber"]
        previous_id = state["previousMediaJobId"]
        approval_id = state["creativeApprovalId"]
        creation_source = "CREATIVE_APPROVAL" if approval_id else "LEGACY_APPROVED_CREATIVE"
        source_key = approval_id or creative.id
        creation_key = f"MEDIA_HANDOFF:{source_key}:{render_type}:{fingerprint}:ATTEMPT:{attempt_number}"
        active_key = f"MEDIA_ACTIVE:{creative.id}"
        width, height = RENDER_PROFILES[render_type]
        row = MediaJob(
            creative_id=creative.id, render_type=render_type, status="QUEUED",
            width=width, height=height, fps=30, video_codec="h264", audio_codec="aac",
            expected_duration_seconds=creative.estimated_duration_seconds,
            progress_percent=0, validation_details={"inputFingerprint": fingerprint},
            creation_source=creation_source, creation_key=creation_key, active_key=active_key,
            source_creative_approval_id=approval_id, input_fingerprint=fingerprint,
            attempt_number=attempt_number, previous_media_job_id=previous_id,
        )
        try:
            self.db.add(row)
            self.db.flush()
            campaign_id = creative.campaign_id
            log_decision(self.db, "OPERATOR", "MEDIA_JOB", "MEDIA_JOB_CREATED", row.id, metadata={
                "creativeId": creative.id, "campaignId": campaign_id,
                "creativeApprovalId": approval_id, "renderType": render_type,
                "inputFingerprint": fingerprint, "attemptNumber": attempt_number,
                "previousMediaJobId": previous_id, "creationSource": creation_source,
            })
            self.db.commit()
            self.db.refresh(row)
            return row
        except (IntegrityError, OperationalError):
            self.db.rollback()
            same_attempt = self.db.scalar(select(MediaJob).where(MediaJob.creation_key == creation_key))
            if same_attempt and same_attempt.status in ACTIVE_STATUSES:
                if same_attempt.render_type == render_type and self._fingerprint(same_attempt) == fingerprint:
                    return same_attempt
                raise _error("MEDIA_JOB_ALREADY_ACTIVE", "Já existe uma produção ativa diferente para este criativo.")
            if same_attempt and same_attempt.status in TERMINAL:
                return self.create(creative_id, render_type)
            return self._conflict_after_race(creative.id, render_type, fingerprint)
        except Exception:
            self.db.rollback()
            raise
