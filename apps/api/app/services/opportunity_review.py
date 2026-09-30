from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from apps.api.app.db.models import CuratorCandidate
from apps.api.app.services.operations import log_decision


VALID_STATUSES = {"PENDING", "INVESTIGATE", "DISMISSED", "COMMERCIAL_REVIEW"}


class OpportunityReviewService:
    def __init__(self, db: Session):
        self.db = db

    def review(self, candidate_id: str, status: str, reason: str | None = None) -> dict:
        candidate = self.db.get(CuratorCandidate, candidate_id)
        if not candidate:
            raise HTTPException(404, "Candidato não encontrado")
        if status not in VALID_STATUSES:
            raise HTTPException(422, "Status de revisão inválido")

        reason = reason.strip() if reason else None
        if reason == "":
            reason = None
        previous_status = candidate.opportunity_review_status or "PENDING"
        previous_reason = candidate.opportunity_review_reason
        next_reason = None if status == "PENDING" else reason
        if previous_status == status and previous_reason == next_reason:
            return self.public(candidate)

        candidate.opportunity_review_status = status
        candidate.opportunity_review_reason = next_reason
        candidate.opportunity_reviewed_at = None if status == "PENDING" else datetime.now(timezone.utc)
        action = "OPPORTUNITY_REVIEW_RESET_PENDING" if status == "PENDING" else f"OPPORTUNITY_REVIEW_{status}"
        log_decision(
            self.db, "OPERATOR", "CURATOR_CANDIDATE", action, candidate.id,
            reason=next_reason,
            metadata={"candidateId": candidate.id, "previousStatus": previous_status, "newStatus": status, "hasReason": bool(next_reason)},
        )
        self.db.commit()
        self.db.refresh(candidate)
        return self.public(candidate)

    @staticmethod
    def public(candidate: CuratorCandidate) -> dict:
        return {
            "candidateId": candidate.id,
            "opportunityReviewStatus": candidate.opportunity_review_status or "PENDING",
            "opportunityReviewedAt": candidate.opportunity_reviewed_at,
            "opportunityReviewReason": candidate.opportunity_review_reason,
        }
