from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.models import CuratorAssessment, CuratorCandidate
from apps.api.app.services.operations import log_decision
from apps.api.app.services.opportunity_orchestration import OpportunityOrchestrationService


DECIDED_STATUSES = {"APPROVED", "REJECTED"}


class CampaignHandoffService:
    """Candidate-level human gate; it deliberately does not create campaigns."""

    def __init__(self, db: Session):
        self.db = db

    def _candidate(self, candidate_id: str) -> CuratorCandidate:
        candidate = self.db.get(CuratorCandidate, candidate_id)
        if not candidate:
            raise HTTPException(404, "Candidato não encontrado")
        return candidate

    def _current_assessment(self, candidate: CuratorCandidate) -> CuratorAssessment | None:
        return self.db.scalar(
            select(CuratorAssessment)
            .where(CuratorAssessment.candidate_id == candidate.id)
            .order_by(CuratorAssessment.assessment_version.desc())
        )

    def _assert_eligible(self, candidate: CuratorCandidate) -> CuratorAssessment:
        if candidate.status == "ARCHIVED":
            raise HTTPException(409, "CANDIDATE_ARCHIVED")
        if candidate.opportunity_review_status != "COMMERCIAL_REVIEW":
            raise HTTPException(409, "COMMERCIAL_REVIEW_REQUIRED")
        if candidate.commercial_analysis_status != "ASSESSMENT_AVAILABLE":
            raise HTTPException(409, "ASSESSMENT_NOT_AVAILABLE")
        assessment = self._current_assessment(candidate)
        if not assessment:
            raise HTTPException(409, "ASSESSMENT_REQUIRED")
        return assessment

    def _public(self, candidate: CuratorCandidate, current: CuratorAssessment | None = None) -> dict:
        current = current if current is not None else self._current_assessment(candidate)
        bound_id = candidate.campaign_handoff_assessment_id
        bound_assessment = self.db.get(CuratorAssessment, bound_id) if bound_id else None
        return {
            "candidateId": candidate.id,
            "status": candidate.campaign_handoff_status or "NOT_DECIDED",
            "assessmentId": bound_id,
            "assessmentVersion": bound_assessment.assessment_version if bound_assessment else None,
            "reviewedAt": candidate.campaign_handoff_reviewed_at,
            "reason": candidate.campaign_handoff_reason,
            "currentAssessmentId": current.id if current else None,
            "currentAssessmentVersion": current.assessment_version if current else None,
            "isCurrentAssessment": bool(bound_id and current and bound_id == current.id),
        }

    def get(self, candidate_id: str) -> dict:
        return self._public(self._candidate(candidate_id))

    def update(self, candidate_id: str, status: str, assessment_id: str | None, reason: str | None) -> dict:
        candidate = self._candidate(candidate_id)
        current = self._assert_eligible(candidate)
        old_status = candidate.campaign_handoff_status or "NOT_DECIDED"
        normalized_reason = reason.strip() if reason else None

        if status == "NOT_DECIDED":
            if old_status == "NOT_DECIDED" and not candidate.campaign_handoff_assessment_id and not candidate.campaign_handoff_reason:
                return self._public(candidate, current)
            candidate.campaign_handoff_status = "NOT_DECIDED"
            candidate.campaign_handoff_assessment_id = None
            candidate.campaign_handoff_reviewed_at = None
            candidate.campaign_handoff_reason = None
            action = "CAMPAIGN_HANDOFF_RESET"
            metadata = {"candidateId": candidate.id, "oldStatus": old_status, "newStatus": "NOT_DECIDED"}
        else:
            if not assessment_id:
                raise HTTPException(422, "ASSESSMENT_ID_REQUIRED")
            if assessment_id != current.id:
                raise HTTPException(409, "ASSESSMENT_CHANGED")
            if old_status == status and candidate.campaign_handoff_assessment_id == current.id and candidate.campaign_handoff_reason == normalized_reason:
                return self._public(candidate, current)
            candidate.campaign_handoff_status = status
            candidate.campaign_handoff_assessment_id = current.id
            candidate.campaign_handoff_reviewed_at = datetime.now(timezone.utc)
            candidate.campaign_handoff_reason = normalized_reason
            action = f"CAMPAIGN_HANDOFF_{status}"
            metadata = {"candidateId": candidate.id, "assessmentId": current.id, "assessmentVersion": current.assessment_version, "oldStatus": old_status, "newStatus": status}

        try:
            log_decision(self.db, "OPERATOR", "CURATOR_CANDIDATE", action, candidate.id, normalized_reason, metadata)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(candidate)
        return self._public(candidate, current)

    def mark_stale_if_superseded(self, candidate: CuratorCandidate, new_assessment: CuratorAssessment) -> bool:
        if candidate.campaign_handoff_status not in DECIDED_STATUSES:
            return False
        if candidate.campaign_handoff_assessment_id == new_assessment.id:
            return False
        old_status = candidate.campaign_handoff_status
        candidate.campaign_handoff_status = "STALE"
        log_decision(
            self.db,
            "SYSTEM",
            "CURATOR_CANDIDATE",
            "CAMPAIGN_HANDOFF_STALE",
            candidate.id,
            metadata={
                "candidateId": candidate.id,
                "assessmentId": candidate.campaign_handoff_assessment_id,
                "newAssessmentId": new_assessment.id,
                "newAssessmentVersion": new_assessment.assessment_version,
                "oldStatus": old_status,
                "newStatus": "STALE",
            },
        )
        return True

    def summary(self) -> dict:
        query = OpportunityOrchestrationService._eligible_query().where(
            CuratorCandidate.opportunity_review_status == "COMMERCIAL_REVIEW",
            CuratorCandidate.commercial_analysis_status == "ASSESSMENT_AVAILABLE",
        )
        counts = {"notDecided": 0, "approved": 0, "rejected": 0, "stale": 0}
        for candidate in self.db.scalars(query):
            key = {
                "APPROVED": "approved",
                "REJECTED": "rejected",
                "STALE": "stale",
            }.get(candidate.campaign_handoff_status or "NOT_DECIDED", "notDecided")
            counts[key] += 1
        return counts
