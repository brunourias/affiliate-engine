import os
import sqlite3
import subprocess
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from apps.api.app.db.models import Campaign, Creative, CuratorAssessment, CuratorCandidate, CuratorEvidence, DecisionLog, MediaJob, PublicationExecution
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.campaign_handoff import CampaignHandoffService
from apps.api.app.services.commercial_analysis import CommercialAnalysisService


class Enrichment:
    def enrich_candidate(self, candidate_id, commit=False):
        return {
            "catalogProductId": "MLB123",
            "observedItemId": "MLB999",
            "commercialEvidenceAvailable": True,
            "sourceStatuses": {"catalog": {"status": "AVAILABLE"}},
        }

    def close(self):
        pass


def candidate(db, identifier, *, review="COMMERCIAL_REVIEW", commercial="ASSESSMENT_AVAILABLE", archived=False, marked=True, triage="TRIAGE_HIGH"):
    row = CuratorCandidate(
        id=identifier, provider="MERCADO_LIVRE", site_id="MLB", source_type="MANUAL", entity_type="PRODUCT",
        external_id=f"MLB{identifier}", working_title="Produto", status="ARCHIVED" if archived else "NEW",
        opportunity_review_status=review, commercial_analysis_status=commercial,
        triage_marked_for_enrichment=marked, triage_status=triage,
    )
    db.add(row)
    db.commit()
    return row


def assessment(db, row, version=1):
    value = CuratorAssessment(
        candidate_id=row.id, assessment_version=version, evidence_status="SUFFICIENT_EVIDENCE", evidence_level="HIGH",
        trust_gate="PASS", trust_reasons=[], trust_warnings=[], recommendation_score=75,
        recommendation_coverage_percent=80, recommendation_label="GOOD", opportunity_score=70,
        opportunity_coverage_percent=70, price_verdict="GOOD_PRICE", price_to_buy_cents=None,
        editorial_verdict="WORTH_IT", recommendation_pillars={}, opportunity_pillars={},
        evidence_ids_used=[], unknown_fields=[], rationale={},
    )
    db.add(value)
    db.commit()
    return value


def eligible(db, identifier="candidate"):
    row = candidate(db, identifier)
    return row, assessment(db, row)


def test_handoff_approves_rejects_and_resets_with_safe_idempotency():
    with SessionLocal() as db:
        row, current = eligible(db)
        service = CampaignHandoffService(db)
        approved = service.update(row.id, "APPROVED", current.id, "Pronto para campanha")
        assert approved["status"] == "APPROVED" and approved["assessmentId"] == current.id and approved["isCurrentAssessment"]
        same = service.update(row.id, "APPROVED", current.id, "Pronto para campanha")
        assert same["status"] == "APPROVED"
        actions = list(db.scalars(select(DecisionLog.action).where(DecisionLog.entity_id == row.id, DecisionLog.action == "CAMPAIGN_HANDOFF_APPROVED")))
        assert len(actions) == 1
        rejected = service.update(row.id, "REJECTED", current.id, "Ainda não")
        assert rejected["status"] == "REJECTED" and rejected["reason"] == "Ainda não"
        reset = service.update(row.id, "NOT_DECIDED", None, None)
        assert reset["status"] == "NOT_DECIDED" and reset["assessmentId"] is None and reset["reviewedAt"] is None


def test_handoff_requires_the_current_assessment_and_eligibility(client):
    with SessionLocal() as db:
        row, current = eligible(db, "current")
        stale = assessment(db, row, 2)
        response = client.patch(f"/api/v1/curator/candidates/{row.id}/campaign-handoff", json={"status": "APPROVED", "assessmentId": current.id})
        assert response.status_code == 409 and response.json()["detail"] == "ASSESSMENT_CHANGED"
        response = client.patch(f"/api/v1/curator/candidates/{row.id}/campaign-handoff", json={"status": "APPROVED"})
        assert response.status_code == 422 and response.json()["detail"] == "ASSESSMENT_ID_REQUIRED"
        blocked = candidate(db, "pending", review="PENDING")
        assert client.patch(f"/api/v1/curator/candidates/{blocked.id}/campaign-handoff", json={"status": "APPROVED", "assessmentId": stale.id}).json()["detail"] == "COMMERCIAL_REVIEW_REQUIRED"
        archived = candidate(db, "archived", archived=True)
        assert client.get(f"/api/v1/curator/candidates/{archived.id}/campaign-handoff").status_code == 200
        assert client.patch(f"/api/v1/curator/candidates/{archived.id}/campaign-handoff", json={"status": "APPROVED", "assessmentId": stale.id}).json()["detail"] == "CANDIDATE_ARCHIVED"


def test_new_assessment_marks_prior_handoff_stale_and_reused_one_does_not():
    with SessionLocal() as db:
        row = candidate(db, "new-version", commercial="NOT_STARTED")
        analysis = CommercialAnalysisService(db, Enrichment())
        first = analysis.analyze(row.id)
        handoff = CampaignHandoffService(db).update(row.id, "APPROVED", first["assessmentId"], None)
        assert handoff["status"] == "APPROVED"
        # With unchanged active evidence, no new assessment means no staleness.
        same = analysis.analyze(row.id)
        assert same["assessmentReused"] is True and db.get(CuratorCandidate, row.id).campaign_handoff_status == "APPROVED"
        db.add(CuratorEvidence(candidate_id=row.id, evidence_type="CURRENT_PRICE", source_kind="OFFICIAL", source_reference="price", value_cents=100, confidence="HIGH", verification_status="VERIFIED"))
        db.commit()
        second = analysis.analyze(row.id)
        saved = db.get(CuratorCandidate, row.id)
        assert second["assessmentVersion"] == 2 and saved.campaign_handoff_status == "STALE"
        assert saved.campaign_handoff_assessment_id == first["assessmentId"]
        assert "CAMPAIGN_HANDOFF_STALE" in set(db.scalars(select(DecisionLog.action).where(DecisionLog.entity_id == row.id)))


def test_summary_uses_same_eligible_commercial_review_universe(client):
    with SessionLocal() as db:
        approved, aa = eligible(db, "approved")
        CampaignHandoffService(db).update(approved.id, "APPROVED", aa.id, None)
        rejected, ar = eligible(db, "rejected")
        CampaignHandoffService(db).update(rejected.id, "REJECTED", ar.id, None)
        stale, astale = eligible(db, "stale")
        stale.campaign_handoff_status = "STALE"
        pending, _ = eligible(db, "pending")
        candidate(db, "excluded-review", review="PENDING")
        candidate(db, "excluded-low", triage="TRIAGE_LOW")
        candidate(db, "excluded-analysis", commercial="EVIDENCE_PARTIAL")
        db.commit()
        response = client.get("/api/v1/curator/opportunities/campaign-handoff/summary")
        assert response.status_code == 200
        assert response.json() == {"notDecided": 1, "approved": 1, "rejected": 1, "stale": 1}
        item = next(x for x in client.get("/api/v1/curator/opportunities?reviewStatus=COMMERCIAL_REVIEW").json() if x["candidateId"] == pending.id)
        assert item["campaignHandoffStatus"] == "NOT_DECIDED"


def test_handoff_has_no_campaign_media_or_publication_side_effects():
    with SessionLocal() as db:
        row, current = eligible(db, "side-effects")
        CampaignHandoffService(db).update(row.id, "APPROVED", current.id, None)
        assert db.scalar(select(Campaign.id)) is None
        assert db.scalar(select(Creative.id)) is None
        assert db.scalar(select(MediaJob.id)) is None
        assert db.scalar(select(PublicationExecution.id)) is None


@pytest.mark.parametrize("review", ["PENDING", "INVESTIGATE", "DISMISSED"])
def test_every_non_commercial_review_status_is_ineligible(review):
    with SessionLocal() as db:
        row = candidate(db, f"review-{review}", review=review)
        with pytest.raises(HTTPException, match="COMMERCIAL_REVIEW_REQUIRED"):
            CampaignHandoffService(db).update(row.id, "APPROVED", "does-not-matter", None)


@pytest.mark.parametrize("commercial", ["NOT_STARTED", "WAITING_FOR_OFFER", "EVIDENCE_PARTIAL", "FAILED"])
def test_commercial_review_requires_assessment_available(commercial):
    with SessionLocal() as db:
        row = candidate(db, f"analysis-{commercial}", commercial=commercial)
        with pytest.raises(HTTPException, match="ASSESSMENT_NOT_AVAILABLE"):
            CampaignHandoffService(db).update(row.id, "APPROVED", "does-not-matter", None)


def test_assessment_available_without_assessment_is_ineligible():
    with SessionLocal() as db:
        row = candidate(db, "no-assessment")
        with pytest.raises(HTTPException, match="ASSESSMENT_REQUIRED"):
            CampaignHandoffService(db).update(row.id, "APPROVED", "does-not-matter", None)


def test_approved_and_rejected_preserve_the_commercial_review_state():
    with SessionLocal() as db:
        row, current = eligible(db, "states")
        service = CampaignHandoffService(db)
        approved = service.update(row.id, "APPROVED", current.id, "Motivo aprovado")
        saved = db.get(CuratorCandidate, row.id)
        assert approved["assessmentVersion"] == 1 and approved["reviewedAt"] and approved["reason"] == "Motivo aprovado"
        assert saved.opportunity_review_status == "COMMERCIAL_REVIEW" and saved.commercial_analysis_status == "ASSESSMENT_AVAILABLE"
        rejected = service.update(row.id, "REJECTED", current.id, "Motivo rejeitado")
        assert rejected["status"] == "REJECTED" and rejected["assessmentId"] == current.id and rejected["reason"] == "Motivo rejeitado"


def test_repeating_rejected_and_reset_do_not_duplicate_logs():
    with SessionLocal() as db:
        row, current = eligible(db, "idempotency")
        service = CampaignHandoffService(db)
        service.update(row.id, "REJECTED", current.id, "Não agora")
        service.update(row.id, "REJECTED", current.id, "Não agora")
        service.update(row.id, "NOT_DECIDED", None, None)
        service.update(row.id, "NOT_DECIDED", None, None)
        actions = list(db.scalars(select(DecisionLog.action).where(DecisionLog.entity_id == row.id)))
        assert actions.count("CAMPAIGN_HANDOFF_REJECTED") == 1
        assert actions.count("CAMPAIGN_HANDOFF_RESET") == 1


@pytest.mark.parametrize("decision", ["APPROVED", "REJECTED"])
def test_stale_preserves_original_snapshot_and_can_be_decided_again(decision):
    with SessionLocal() as db:
        row, v1 = eligible(db, f"stale-{decision}")
        service = CampaignHandoffService(db)
        initial = service.update(row.id, decision, v1.id, "Razão original")
        reviewed_at = initial["reviewedAt"]
        v2 = assessment(db, row, 2)
        assert service.mark_stale_if_superseded(row, v2) is True
        db.commit(); db.refresh(row)
        stale = service.get(row.id)
        assert stale["status"] == "STALE" and stale["assessmentId"] == v1.id and stale["reviewedAt"] == reviewed_at
        assert stale["reason"] == "Razão original" and stale["isCurrentAssessment"] is False
        redone = service.update(row.id, decision, v2.id, "Razão nova")
        assert redone["status"] == decision and redone["assessmentId"] == v2.id and redone["isCurrentAssessment"]


def test_api_rejects_direct_stale_status(client):
    with SessionLocal() as db:
        row, current = eligible(db, "direct-stale")
        response = client.patch(f"/api/v1/curator/candidates/{row.id}/campaign-handoff", json={"status": "STALE", "assessmentId": current.id})
        assert response.status_code == 422


def test_update_rolls_back_if_decision_log_cannot_be_written(monkeypatch):
    with SessionLocal() as db:
        row, current = eligible(db, "rollback")
        def broken_log(*args, **kwargs):
            raise RuntimeError("log unavailable")
        monkeypatch.setattr("apps.api.app.services.campaign_handoff.log_decision", broken_log)
        with pytest.raises(RuntimeError, match="log unavailable"):
            CampaignHandoffService(db).update(row.id, "APPROVED", current.id, "Não persistir")
        db.rollback()
    with SessionLocal() as fresh:
        saved = fresh.get(CuratorCandidate, "rollback")
        assert saved.campaign_handoff_status == "NOT_DECIDED"
        assert fresh.scalar(select(DecisionLog).where(DecisionLog.entity_id == "rollback", DecisionLog.action == "CAMPAIGN_HANDOFF_APPROVED")) is None


def test_sqlite_fk_cycle_schema_relationship_and_delete_are_safe():
    """The production FK is real; only schema reset briefly disables SQLite checks."""
    with SessionLocal() as db:
        row, current = eligible(db, "fk-cycle")
        assessment_id = current.id
        CampaignHandoffService(db).update(row.id, "APPROVED", current.id, None)
        db.delete(current)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        row = db.get(CuratorCandidate, "fk-cycle")
        db.delete(row)
        db.commit()
        assert db.get(CuratorCandidate, "fk-cycle") is None
        assert db.get(CuratorAssessment, assessment_id) is None


def test_migration_0017_round_trip_on_isolated_sqlite(tmp_path):
    database = tmp_path / "migration-roundtrip.db"
    environment = {**os.environ, "AFFILIATE_DATABASE_URL": f"sqlite:///{database.as_posix()}"}
    root = __import__("pathlib").Path(__file__).resolve().parents[3]
    command = [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini"]
    for target in ("0016_commercial_analysis_state", "0017_campaign_handoff_gate", "0016_commercial_analysis_state", "0017_campaign_handoff_gate"):
        operation = "downgrade" if target == "0016_commercial_analysis_state" and database.exists() else "upgrade"
        completed = subprocess.run([*command, operation, target], cwd=root, env=environment, capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stderr
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(curator_candidates)")}
        foreign_keys = connection.execute("PRAGMA foreign_key_list(curator_candidates)").fetchall()
    assert {"campaign_handoff_status", "campaign_handoff_assessment_id", "campaign_handoff_reviewed_at", "campaign_handoff_reason"}.issubset(columns)
    assert any(row[2] == "curator_assessments" and row[3] == "campaign_handoff_assessment_id" for row in foreign_keys)
