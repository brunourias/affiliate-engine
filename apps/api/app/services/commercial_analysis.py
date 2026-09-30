from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorAssessment, CuratorCandidate, CuratorEvidence
from apps.api.app.services.assessment import CuratorAssessmentService
from apps.api.app.services.curator import stale
from apps.api.app.services.evidence_enrichment import CandidateEvidenceEnrichmentService
from apps.api.app.services.operations import log_decision


class CommercialAnalysisService:
    def __init__(self, db: Session, enrichment=None):
        self.db = db
        self.enrichment = enrichment or CandidateEvidenceEnrichmentService(db)
        self.owns_enrichment = enrichment is None

    def close(self):
        if self.owns_enrichment:
            self.enrichment.close()

    def analyze(self, candidate_id: str) -> dict:
        candidate = self.db.get(CuratorCandidate, candidate_id)
        if not candidate:
            raise HTTPException(404, "Candidato não encontrado")
        if candidate.opportunity_review_status != "COMMERCIAL_REVIEW":
            raise HTTPException(409, "COMMERCIAL_REVIEW_REQUIRED")
        log_decision(self.db, "SYSTEM", "CURATOR_CANDIDATE", "COMMERCIAL_ANALYSIS_STARTED", candidate.id, metadata={"candidateId": candidate.id, "catalogProductId": candidate.external_id})
        try:
            result = self.enrichment.enrich_candidate(candidate.id, commit=False)
            response = self._finish(candidate, result)
            self.db.commit()
            return response
        except HTTPException:
            raise
        except Exception:
            self.db.rollback()
            candidate = self.db.get(CuratorCandidate, candidate_id)
            candidate.commercial_analysis_status = "FAILED"; candidate.commercial_analysis_last_run_at = datetime.now(timezone.utc); candidate.commercial_analysis_blocker = "ENRICHMENT_FAILED"
            log_decision(self.db, "SYSTEM", "CURATOR_CANDIDATE", "COMMERCIAL_ANALYSIS_FAILED", candidate.id, metadata={"candidateId": candidate.id, "commercialAnalysisStatus": "FAILED"})
            self.db.commit()
            return self._public(candidate, None, None, False, False)

    def run(self) -> dict:
        rows = list(self.db.scalars(self._commercial_review_query().order_by(CuratorCandidate.id).limit(max(1, settings.commercial_analysis_batch_limit))))
        results = [self.analyze(row.id) for row in rows]
        failed = sum(item["commercialAnalysisStatus"] == "FAILED" for item in results)
        status = "FAILED" if rows and failed == len(rows) else "PARTIAL" if failed else "COMPLETED"
        payload = {"status": status, "requested": len(rows), "processed": len(results), "assessmentAvailable": sum(x["commercialAnalysisStatus"] == "ASSESSMENT_AVAILABLE" for x in results), "waitingForOffer": sum(x["commercialAnalysisStatus"] == "WAITING_FOR_OFFER" for x in results), "evidencePartial": sum(x["commercialAnalysisStatus"] == "EVIDENCE_PARTIAL" for x in results), "failed": failed, "candidates": results}
        log_decision(self.db, "SYSTEM", "SYSTEM", f"COMMERCIAL_ANALYSIS_BATCH_{status}", metadata={key: payload[key] for key in ("requested", "processed", "assessmentAvailable", "waitingForOffer", "evidencePartial", "failed")})
        self.db.commit()
        return payload

    def summary(self) -> dict:
        rows = self.db.scalars(self._commercial_review_query()).all()
        mapping = {"NOT_STARTED": "notStarted", "WAITING_FOR_OFFER": "waitingForOffer", "EVIDENCE_PARTIAL": "evidencePartial", "ASSESSMENT_AVAILABLE": "assessmentAvailable", "FAILED": "failed"}
        result = {value: 0 for value in mapping.values()}
        for row in rows: result[mapping.get(row.commercial_analysis_status or "NOT_STARTED", "notStarted")] += 1
        return result

    @staticmethod
    def _commercial_review_query():
        # The commercial summary and batch must operate on precisely the same
        # eligible opportunity universe shown by /curator/opportunities.
        from apps.api.app.services.opportunity_orchestration import OpportunityOrchestrationService
        return OpportunityOrchestrationService._eligible_query().where(CuratorCandidate.opportunity_review_status == "COMMERCIAL_REVIEW")

    def _finish(self, candidate, enriched):
        item_id = enriched.get("observedItemId")
        binding = self.db.scalar(select(CuratorEvidence).where(CuratorEvidence.candidate_id == candidate.id, CuratorEvidence.evidence_type == "MARKETPLACE_LISTING_BINDING").order_by(CuratorEvidence.observed_at.desc()))
        binding_value = dict(binding.value_json or {}) if binding else {}
        source_item = binding_value.get("sourceItemId") or binding_value.get("itemId") or item_id
        offer_source = "EXPLICIT_BINDING" if binding_value.get("sourceItemId") or binding_value.get("itemId") else "OFFICIAL_BUY_BOX" if item_id else None
        if not source_item:
            candidate.commercial_analysis_status = "WAITING_FOR_OFFER"; candidate.commercial_analysis_blocker = "OFFER_REQUIRED"
            action = "COMMERCIAL_ANALYSIS_WAITING_FOR_OFFER"; assessment = None; reused = False
        elif not enriched.get("commercialEvidenceAvailable"):
            statuses = enriched.get("sourceStatuses", {})
            forbidden = any(value.get("status") == "FORBIDDEN" for value in statuses.values())
            candidate.commercial_analysis_status = "EVIDENCE_PARTIAL"; candidate.commercial_analysis_blocker = "ITEM_DETAILS_FORBIDDEN" if forbidden else "COMMERCIAL_DATA_UNAVAILABLE"
            action = "COMMERCIAL_ANALYSIS_EVIDENCE_PARTIAL"; assessment = None; reused = False
        else:
            assessment, reused = self._assessment(candidate)
            candidate.commercial_analysis_status = "ASSESSMENT_AVAILABLE"; candidate.commercial_analysis_blocker = None
            action = "COMMERCIAL_ANALYSIS_ASSESSMENT_REUSED" if reused else "COMMERCIAL_ANALYSIS_ASSESSMENT_CREATED"
        candidate.commercial_analysis_last_run_at = datetime.now(timezone.utc)
        log_decision(self.db, "SYSTEM", "CURATOR_CANDIDATE", action, candidate.id, metadata={"candidateId": candidate.id, "catalogProductId": enriched.get("catalogProductId"), "sourceItemId": source_item, "offerSource": offer_source, "commercialAnalysisStatus": candidate.commercial_analysis_status, "assessmentId": assessment.id if assessment else None, "assessmentReused": reused, "sourceStatuses": {key: value.get("status") for key, value in enriched.get("sourceStatuses", {}).items()}})
        return self._public(candidate, enriched, assessment, reused, bool(source_item), source_item, offer_source)

    def _assessment(self, candidate):
        ids = sorted(e.id for e in self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id == candidate.id)) if not stale(e))
        latest = self.db.scalar(select(CuratorAssessment).where(CuratorAssessment.candidate_id == candidate.id).order_by(CuratorAssessment.assessment_version.desc()))
        if latest and sorted(latest.evidence_ids_used or []) == ids:
            return latest, True
        assessment = CuratorAssessmentService(self.db).assess(candidate, commit=False)
        # A reused assessment remains an approved snapshot. Only a genuinely
        # new evidence-based version invalidates a prior human decision.
        from apps.api.app.services.campaign_handoff import CampaignHandoffService
        CampaignHandoffService(self.db).mark_stale_if_superseded(candidate, assessment)
        return assessment, False

    def _public(self, candidate, enriched, assessment, reused, has_offer=False, source_item=None, offer_source=None):
        output = {"candidateId": candidate.id, "opportunityReviewStatus": candidate.opportunity_review_status, "commercialAnalysisStatus": candidate.commercial_analysis_status, "commercialAnalysisLastRunAt": candidate.commercial_analysis_last_run_at, "commercialAnalysisBlocker": candidate.commercial_analysis_blocker, "catalogProductId": enriched.get("catalogProductId") if enriched else candidate.external_id, "sourceItemId": source_item, "offerSource": offer_source, "commercialEvidenceAvailable": bool(enriched and enriched.get("commercialEvidenceAvailable")), "sourceStatuses": enriched.get("sourceStatuses") if enriched else {}, "evidenceAdded": enriched.get("evidenceAdded", 0) if enriched else 0, "evidenceChanged": enriched.get("evidenceChanged", 0) if enriched else 0, "evidenceUnchanged": enriched.get("evidenceUnchanged", 0) if enriched else 0, "assessmentId": assessment.id if assessment else None, "assessmentVersion": assessment.assessment_version if assessment else None, "assessmentReused": reused}
        if assessment:
            output.update({"trustGate": assessment.trust_gate, "recommendationScore": assessment.recommendation_score, "recommendationCoveragePercent": assessment.recommendation_coverage_percent, "opportunityScore": assessment.opportunity_score, "opportunityCoveragePercent": assessment.opportunity_coverage_percent, "priceVerdict": assessment.price_verdict, "editorialVerdict": assessment.editorial_verdict})
        return output
