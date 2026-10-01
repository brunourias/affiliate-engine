"""Transactional decision handling for Campaign approvals."""

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from fastapi import HTTPException

from apps.api.app.db.models import Approval, Campaign, Notification
from apps.api.app.services.campaigns import readiness
from apps.api.app.services.operations import log_decision, notify, utcnow


INCONSISTENT = {
    "code": "CAMPAIGN_APPROVAL_STATE_INCONSISTENT",
    "message": "O estado da aprovação desta campanha precisa ser revisado.",
}
DECISION_CONFLICT_MESSAGE = "Esta aprovação já recebeu uma decisão diferente."
INVALIDATED_MESSAGE = "A campanha mudou de condição desde o envio e precisa ser revisada antes da aprovação."


def _reason(value: str | None) -> str | None:
    normalized = value.strip() if value is not None else ""
    return normalized or None


class CampaignApprovalDecisionService:
    """Apply a Campaign approval and its audit effects as one database transaction."""

    def __init__(self, db: Session):
        self.db = db

    def _inconsistent(self):
        raise HTTPException(409, INCONSISTENT)

    def _conflict(self, current_status: str):
        raise HTTPException(409, {
            "code": "APPROVAL_DECISION_CONFLICT",
            "message": DECISION_CONFLICT_MESSAGE,
            "currentStatus": current_status,
        })

    def _reload_after_race(self, approval_id: str, requested: str):
        self.db.rollback()
        current = self.db.get(Approval, approval_id)
        if current and current.status == requested:
            return current
        if current and current.status in {"APPROVED", "REJECTED"}:
            self._conflict(current.status)
        return None

    def _finish_decision(self, item: Approval, campaign: Campaign, status: str,
                         now, reason: str | None) -> Approval:
        try:
            if status == "APPROVED":
                current_readiness = readiness(self.db, campaign)
                if current_readiness["blockers"]:
                    self.db.rollback()
                    raise HTTPException(409, {
                        "code": "CAMPAIGN_APPROVAL_INVALIDATED",
                        "message": INVALIDATED_MESSAGE,
                        "blockers": current_readiness["blockers"],
                    })

            campaign_update = self.db.execute(update(Campaign).where(
                Campaign.id == campaign.id,
                Campaign.status == "PENDING_APPROVAL",
            ).values(
                status=status,
                approved_at=now if status == "APPROVED" else None,
                rejected_at=now if status == "REJECTED" else None,
                updated_at=now,
            )).rowcount
            if campaign_update != 1:
                self.db.rollback()
                current = self.db.get(Campaign, campaign.id)
                if current and current.status != "PENDING_APPROVAL":
                    self._conflict(current.status)
                self._inconsistent()

            action_suffix = "APPROVED" if status == "APPROVED" else "REJECTED"
            log_decision(self.db, "OPERATOR", "APPROVAL", f"APPROVAL_{action_suffix}", item.id, reason,
                         {"type": item.type, "entityType": item.entity_type, "entityId": item.entity_id})
            log_decision(self.db, "OPERATOR", "CAMPAIGN", f"CAMPAIGN_{action_suffix}", campaign.id, reason,
                         {"approvalId": item.id, "campaignId": campaign.id, "assessmentId": campaign.assessment_id})
            notify(self.db, "SUCCESS" if status == "APPROVED" else "WARNING",
                   f"Solicitação {status.lower()}", item.title, "APPROVAL", {"approvalId": item.id})
            self.db.commit()
            self.db.refresh(item)
            return item
        except Exception:
            self.db.rollback()
            raise

    def decide(self, approval_id: str, status: str, reason: str | None = None) -> Approval:
        if status not in {"APPROVED", "REJECTED"}:
            raise ValueError("Campaign approval decisions must be APPROVED or REJECTED")

        item = self.db.get(Approval, approval_id)
        if not item:
            raise HTTPException(404, "Aprovação não encontrada")

        if item.type != "CAMPAIGN" or item.entity_type != "CAMPAIGN" or not item.entity_id:
            self._inconsistent()

        # Exact replays are read-only: they must not update timestamps or emit effects.
        if item.status == status:
            return item
        if item.status in {"APPROVED", "REJECTED"}:
            campaign = self.db.get(Campaign, item.entity_id)
            if campaign and campaign.status == "PENDING_APPROVAL":
                active_pending = self.db.scalar(select(Approval.id).where(
                    Approval.type == "CAMPAIGN", Approval.entity_type == "CAMPAIGN",
                    Approval.entity_id == campaign.id, Approval.status == "PENDING",
                ).limit(1))
                if active_pending is None:
                    self._inconsistent()
            self._conflict(item.status)

        campaign = self.db.get(Campaign, item.entity_id)
        if not campaign or campaign.status != "PENDING_APPROVAL":
            self._inconsistent()

        pending = list(self.db.scalars(select(Approval).where(
            Approval.type == "CAMPAIGN",
            Approval.entity_type == "CAMPAIGN",
            Approval.entity_id == campaign.id,
            Approval.status == "PENDING",
        )))
        if len(pending) != 1 or pending[0].id != item.id:
            self._inconsistent()

        now = utcnow()
        normalized_reason = _reason(reason)
        try:
            # Compare-and-swap is the single-writer gate. The campaign transition,
            # audit records and notification remain in this same transaction.
            acquired = self.db.execute(update(Approval).where(
                Approval.id == item.id,
                Approval.type == "CAMPAIGN",
                Approval.entity_type == "CAMPAIGN",
                Approval.entity_id == campaign.id,
                Approval.status == "PENDING",
            ).values(status=status, decided_at=now, updated_at=now, decision_reason=normalized_reason)).rowcount
        except OperationalError:
            replay = self._reload_after_race(approval_id, status)
            if replay:
                return replay
            raise

        if acquired != 1:
            replay = self._reload_after_race(approval_id, status)
            if replay:
                return replay
            item = self.db.get(Approval, approval_id)
            if item and item.status in {"APPROVED", "REJECTED"}:
                self._conflict(item.status)
            self._inconsistent()

        self.db.expire(item)
        item = self.db.get(Approval, approval_id)
        campaign = self.db.get(Campaign, campaign.id)

        return self._finish_decision(item, campaign, status, now, normalized_reason)
