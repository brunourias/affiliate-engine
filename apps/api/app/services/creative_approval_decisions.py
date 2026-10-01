"""Atomic decisions for Creative review approvals."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from apps.api.app.db.models import Approval, Creative
from apps.api.app.services.creatives import readiness
from apps.api.app.services.operations import log_decision, notify


INCONSISTENT = {
    "code": "CREATIVE_APPROVAL_STATE_INCONSISTENT",
    "message": "O estado da aprovação deste criativo precisa ser revisado.",
}
INVALIDATED_MESSAGE = "O criativo ou o contexto da campanha mudou desde o envio e precisa ser revisado antes da aprovação."
CONFLICT_MESSAGE = "Esta aprovação já recebeu uma decisão diferente."


def _reason(value: str | None) -> str | None:
    normalized = value.strip() if value is not None else ""
    return normalized or None


class CreativeApprovalDecisionService:
    """Keep Approval, Creative, audit logs and notification in one transaction."""

    def __init__(self, db: Session):
        self.db = db

    def _inconsistent(self):
        raise HTTPException(409, INCONSISTENT)

    def _conflict(self, status: str):
        raise HTTPException(409, {
            "code": "APPROVAL_DECISION_CONFLICT",
            "message": CONFLICT_MESSAGE,
            "currentStatus": status,
        })

    def _pending_for(self, creative_id: str) -> list[Approval]:
        return list(self.db.scalars(select(Approval).where(
            Approval.type == "CREATIVE",
            Approval.entity_type == "CREATIVE",
            Approval.entity_id == creative_id,
            Approval.status == "PENDING",
        ).order_by(Approval.created_at, Approval.id)))

    def _after_race(self, approval_id: str, requested: str):
        self.db.rollback()
        item = self.db.get(Approval, approval_id)
        if item and item.status == requested:
            creative = self.db.get(Creative, item.entity_id) if item.entity_id else None
            if creative and creative.status == requested:
                return item
            self._inconsistent()
        if item and item.status in {"APPROVED", "REJECTED"}:
            self._conflict(item.status)
        return None

    def decide(self, approval_id: str, status: str, reason: str | None = None) -> Approval:
        if status not in {"APPROVED", "REJECTED"}:
            raise ValueError("Creative approval decisions must be APPROVED or REJECTED")

        item = self.db.get(Approval, approval_id)
        if not item:
            raise HTTPException(404, "Aprovação não encontrada")
        if item.type != "CREATIVE" or item.entity_type != "CREATIVE" or not item.entity_id:
            self._inconsistent()
        creative = self.db.get(Creative, item.entity_id)
        if not creative:
            self._inconsistent()

        # Idempotent replays are read-only, but only if both records agree.
        if item.status == status:
            if creative.status != status:
                self._inconsistent()
            return item
        if item.status in {"APPROVED", "REJECTED"}:
            self._conflict(item.status)
        if item.status != "PENDING" or creative.status != "READY_FOR_REVIEW":
            self._inconsistent()

        pending = self._pending_for(creative.id)
        if len(pending) != 1 or pending[0].id != item.id:
            self._inconsistent()

        current_readiness = readiness(self.db, creative) if status == "APPROVED" else None
        if current_readiness and current_readiness["blockers"]:
            self.db.rollback()
            raise HTTPException(409, {
                "code": "CREATIVE_APPROVAL_INVALIDATED",
                "message": INVALIDATED_MESSAGE,
                "blockers": current_readiness["blockers"],
            })

        now = datetime.now(timezone.utc)
        normalized_reason = _reason(reason)
        try:
            acquired = self.db.execute(update(Approval).where(
                Approval.id == item.id,
                Approval.type == "CREATIVE",
                Approval.entity_type == "CREATIVE",
                Approval.entity_id == creative.id,
                Approval.status == "PENDING",
            ).values(status=status, decision_reason=normalized_reason,
                     decided_at=now, updated_at=now)).rowcount
            if acquired != 1:
                replay = self._after_race(item.id, status)
                if replay:
                    return replay
                current = self.db.get(Approval, item.id)
                if current and current.status in {"APPROVED", "REJECTED"}:
                    self._conflict(current.status)
                self._inconsistent()

            creative_update = self.db.execute(update(Creative).where(
                Creative.id == creative.id,
                Creative.status == "READY_FOR_REVIEW",
            ).values(status=status,
                     approved_at=now if status == "APPROVED" else None,
                     rejected_at=now if status == "REJECTED" else None,
                     updated_at=now)).rowcount
            if creative_update != 1:
                self.db.rollback()
                self._inconsistent()

            log_decision(self.db, "OPERATOR", "APPROVAL", f"APPROVAL_{status}", item.id,
                         normalized_reason, {"type": item.type, "entityType": item.entity_type,
                                             "entityId": item.entity_id})
            log_decision(self.db, "OPERATOR", "CREATIVE", f"CREATIVE_{status}", creative.id,
                         normalized_reason, {"approvalId": item.id, "creativeId": creative.id,
                                             "campaignId": creative.campaign_id,
                                             "experimentId": creative.experiment_id,
                                             "sourceCampaignApprovalId": creative.source_campaign_approval_id,
                                             "sourceAssessmentId": creative.source_assessment_id})
            notify(self.db, "SUCCESS" if status == "APPROVED" else "WARNING",
                   f"Solicitação {status.lower()}", item.title, "APPROVAL", {"approvalId": item.id})
            self.db.commit()
            self.db.refresh(item)
            return item
        except OperationalError:
            replay = self._after_race(item.id, status)
            if replay:
                return replay
            raise
        except Exception:
            self.db.rollback()
            raise
