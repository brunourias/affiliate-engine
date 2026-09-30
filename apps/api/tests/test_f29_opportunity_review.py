from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.db.models import CuratorCandidate, DecisionLog
from apps.api.app.db.session import SessionLocal
from apps.api.app.main import app
from apps.api.app.services.opportunity_orchestration import OpportunityOrchestrationService
from apps.api.app.services.opportunity_review import OpportunityReviewService


def candidate(db, identifier, score=90, triage="TRIAGE_HIGH", marked=True, archived=False):
    row = CuratorCandidate(
        id=identifier, provider="MERCADO_LIVRE", site_id="MLB", source_type="CATALOG_DISCOVERY",
        entity_type="PRODUCT", external_id=f"MLB{identifier[-1] * 6}", working_title=identifier,
        status="ARCHIVED" if archived else "NEW", triage_score=score, triage_status=triage,
        triage_marked_for_enrichment=marked,
    )
    db.add(row)
    db.flush()
    return row


def test_pending_default_queue_and_review_transitions():
    with SessionLocal() as db:
        row = candidate(db, "candidate-a")
        db.commit()
        service = OpportunityReviewService(db)
        assert [item["candidateId"] for item in OpportunityOrchestrationService(db).queue(10)] == [row.id]

        reviewed = service.review(row.id, "INVESTIGATE", "  verificar oferta  ")
        assert reviewed["opportunityReviewStatus"] == "INVESTIGATE"
        assert reviewed["opportunityReviewReason"] == "verificar oferta"
        assert reviewed["opportunityReviewedAt"] is not None
        assert OpportunityOrchestrationService(db).queue(10) == []

        reset = service.review(row.id, "PENDING")
        assert reset["opportunityReviewStatus"] == "PENDING"
        assert reset["opportunityReviewedAt"] is None and reset["opportunityReviewReason"] is None
        assert [item["candidateId"] for item in OpportunityOrchestrationService(db).queue(10)] == [row.id]


def test_review_filters_summary_and_ineligible_candidates():
    with SessionLocal() as db:
        pending = candidate(db, "pending-a")
        investigate = candidate(db, "investigate-b")
        dismissed = candidate(db, "dismissed-c")
        commercial = candidate(db, "commercial-d")
        candidate(db, "low-e", triage="TRIAGE_LOW")
        candidate(db, "archived-f", archived=True)
        candidate(db, "unmarked-g", marked=False)
        db.commit()
        service = OpportunityReviewService(db)
        service.review(investigate.id, "INVESTIGATE")
        service.review(dismissed.id, "DISMISSED")
        service.review(commercial.id, "COMMERCIAL_REVIEW")
        queue = OpportunityOrchestrationService(db)
        assert [item["candidateId"] for item in queue.queue(10)] == [pending.id]
        assert [item["candidateId"] for item in queue.queue(10, "INVESTIGATE")] == [investigate.id]
        assert [item["candidateId"] for item in queue.queue(10, "DISMISSED")] == [dismissed.id]
        assert [item["candidateId"] for item in queue.queue(10, "COMMERCIAL_REVIEW")] == [commercial.id]
        assert {item["candidateId"] for item in queue.queue(10, "ALL")} == {pending.id, investigate.id, dismissed.id, commercial.id}
        assert queue.review_summary() == {"pending": 1, "investigate": 1, "dismissed": 1, "commercialReview": 1}
        assert db.get(CuratorCandidate, dismissed.id).status == "NEW"


def test_review_is_idempotent_and_logs_changes_only():
    with SessionLocal() as db:
        row = candidate(db, "candidate-a")
        db.commit()
        service = OpportunityReviewService(db)
        service.review(row.id, "DISMISSED", "não seguir")
        service.review(row.id, "DISMISSED", "não seguir")
        logs = list(db.scalars(select(DecisionLog).where(DecisionLog.entity_id == row.id, DecisionLog.action == "OPPORTUNITY_REVIEW_DISMISSED")))
        assert len(logs) == 1
        assert logs[0].metadata_["previousStatus"] == "PENDING"
        assert logs[0].metadata_["newStatus"] == "DISMISSED"
        assert logs[0].metadata_["hasReason"] is True


def test_review_endpoint_validates_status_and_preserves_candidate():
    with SessionLocal() as db:
        row = candidate(db, "candidate-a")
        db.commit()
        client = TestClient(app)
        response = client.patch(f"/api/v1/curator/candidates/{row.id}/opportunity-review", json={"status": "COMMERCIAL_REVIEW", "reason": "  "})
        assert response.status_code == 200
        assert response.json()["opportunityReviewStatus"] == "COMMERCIAL_REVIEW"
        assert response.json()["opportunityReviewReason"] is None
        invalid = client.patch(f"/api/v1/curator/candidates/{row.id}/opportunity-review", json={"status": "ARBITRARY"})
        assert invalid.status_code == 422
        assert db.get(CuratorCandidate, row.id).status == "NEW"
