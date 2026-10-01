from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from apps.api.app.db.models import (
    Approval, Campaign, CampaignAngle, CampaignChannel, CampaignExperiment,
    Creative, CreativeScene, CuratorAssessment, CuratorCandidate,
    DecisionLog, MediaJob, PublicationExecution,
)
from apps.api.app.db.session import SessionLocal


def seed_campaign(*, status="APPROVED", channels=("TIKTOK",), approved_count=1,
                  ready=True, requires_spend=False):
    with SessionLocal() as db:
        candidate = CuratorCandidate(provider="OTHER", source_type="MANUAL", entity_type="MANUAL", working_title="Produto de teste")
        db.add(candidate)
        db.flush()
        assessment = CuratorAssessment(
            candidate_id=candidate.id, assessment_version=1, evidence_status="SUFFICIENT_EVIDENCE",
            evidence_level="PUBLIC_VERIFIED", trust_gate="PASS", trust_reasons=[], trust_warnings=[],
            recommendation_score=80, recommendation_coverage_percent=90, recommendation_label="GOOD",
            opportunity_score=75, opportunity_coverage_percent=80, price_verdict="GOOD_PRICE",
            editorial_verdict="WORTH_IT", recommendation_pillars={}, opportunity_pillars={},
            evidence_ids_used=[], unknown_fields=[], rationale={},
        )
        db.add(assessment)
        db.flush()
        campaign = Campaign(
            candidate_id=candidate.id, assessment_id=assessment.id, name="Campanha teste", status=status,
            objective="EDUCATION", editorial_verdict_snapshot="WORTH_IT", trust_gate_snapshot="PASS",
            recommendation_score_snapshot=80, opportunity_score_snapshot=75, price_verdict_snapshot="GOOD_PRICE",
            campaign_priority="HIGH", target_audience="Pessoas interessadas", editorial_positioning="Compra consciente",
            primary_message="Compare as informações disponíveis" if ready else None, cta_strategy="Veja os detalhes",
            disclosure_text="Conteúdo com link de afiliado.", requires_financial_spend=requires_spend,
            trust_warnings_snapshot=[], required_disclosures=[], required_warnings=[], forbidden_claims=[],
        )
        db.add(campaign)
        db.flush()
        for channel in channels:
            db.add(CampaignChannel(campaign_id=campaign.id, channel=channel, enabled=True))
        disabled_channel = None
        if "FACEBOOK_REELS" not in channels:
            disabled_channel = CampaignChannel(campaign_id=campaign.id, channel="FACEBOOK_REELS", enabled=False)
            db.add(disabled_channel)
        db.flush()
        angle = CampaignAngle(campaign_id=campaign.id, angle_type="SMART_BUYING", title="Compra consciente", premise="Compare detalhes", status="ACTIVE")
        db.add(angle)
        db.flush()
        experiment = CampaignExperiment(campaign_id=campaign.id, angle_id=angle.id, hypothesis="Compare antes de escolher", status="PLANNED", target_channel=None)
        db.add(experiment)
        for _ in range(approved_count):
            db.add(Approval(type="CAMPAIGN", status="APPROVED", title="Aprovação humana", description="Snapshot auditável", entity_type="CAMPAIGN", entity_id=campaign.id, requested_payload={}))
        db.commit()
        return {"campaign": campaign.id, "candidate": candidate.id, "assessment": assessment.id,
                "angle": angle.id, "experiment": experiment.id, "disabledChannel": disabled_channel.id if disabled_channel else None}


def detail(response):
    return response.json().get("detail", {})


@pytest.mark.parametrize("status", ["DRAFT", "PENDING_APPROVAL", "REJECTED", "PAUSED", "ARCHIVED"])
def test_non_approved_campaign_states_cannot_create_creative(client, status):
    ids = seed_campaign(status=status)
    response = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={})
    assert response.status_code == 409
    assert detail(response)["code"] == "CAMPAIGN_NOT_APPROVED"
    assert client.get(f"/api/v1/campaigns/{ids['campaign']}/creative-handoff").json()["state"] == "NOT_ELIGIBLE"


def test_approved_campaign_creates_empty_traced_creative_and_only_one_creation_log(client):
    ids = seed_campaign()
    response = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={"name": "Criativo inicial"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["generationMode"] == "MANUAL"
    assert body["targetChannel"] == "TIKTOK"
    assert body["creationSource"] == "CAMPAIGN_APPROVAL"
    assert body["sourceCampaignApprovalId"]
    assert body["sourceAssessmentId"] == ids["assessment"]
    assert body["creationKey"] == f"CAMPAIGN_APPROVAL:{body['sourceCampaignApprovalId']}:BASE"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(CreativeScene).where(CreativeScene.creative_id == body["id"])) == 0
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_type == "CREATIVE", Approval.entity_id == body["id"])) == 0
        assert db.scalar(select(func.count()).select_from(MediaJob).where(MediaJob.creative_id == body["id"])) == 0
        assert db.scalar(select(func.count()).select_from(PublicationExecution).where(PublicationExecution.creative_id == body["id"])) == 0
        logs = list(db.scalars(select(DecisionLog).where(DecisionLog.action == "CREATIVE_CREATED", DecisionLog.entity_id == body["id"])))
        assert len(logs) == 1
        assert logs[0].metadata_["campaignApprovalId"] == body["sourceCampaignApprovalId"]
        assert logs[0].metadata_["assessmentId"] == ids["assessment"]


def test_approval_is_required_and_ambiguous_approvals_block(client):
    missing = seed_campaign(approved_count=0)
    response = client.post(f"/api/v1/creatives/from-campaign/{missing['campaign']}", json={})
    assert response.status_code == 409 and detail(response)["code"] == "CAMPAIGN_APPROVAL_REQUIRED"
    ambiguous = seed_campaign(approved_count=2)
    response = client.post(f"/api/v1/creatives/from-campaign/{ambiguous['campaign']}", json={})
    assert response.status_code == 409 and detail(response)["code"] == "CAMPAIGN_APPROVAL_STATE_INCONSISTENT"
    historical_rejection = seed_campaign()
    with SessionLocal() as db:
        db.add(Approval(type="CAMPAIGN", status="REJECTED", title="Decisão anterior", description="Histórica",
                        entity_type="CAMPAIGN", entity_id=historical_rejection["campaign"], requested_payload={}))
        db.commit()
    assert client.post(f"/api/v1/creatives/from-campaign/{historical_rejection['campaign']}", json={}).status_code == 201


def test_stale_assessment_or_current_readiness_blockers_invalidate_handoff(client):
    ids = seed_campaign()
    with SessionLocal() as db:
        old = db.get(Campaign, ids["campaign"])
        latest = CuratorAssessment(
            candidate_id=old.candidate_id, assessment_version=2, previous_assessment_id=ids["assessment"],
            evidence_status="SUFFICIENT_EVIDENCE", evidence_level="PUBLIC_VERIFIED", trust_gate="PASS",
            trust_reasons=[], trust_warnings=[], recommendation_score=81, recommendation_coverage_percent=90,
            recommendation_label="GOOD", opportunity_score=76, opportunity_coverage_percent=80,
            price_verdict="GOOD_PRICE", editorial_verdict="WORTH_IT", recommendation_pillars={},
            opportunity_pillars={}, evidence_ids_used=[], unknown_fields=[], rationale={},
        )
        db.add(latest)
        db.commit()
    state = client.get(f"/api/v1/campaigns/{ids['campaign']}/creative-handoff").json()
    assert state["state"] == "NOT_ELIGIBLE" and state["reasonCode"] == "ASSESSMENT_OUTDATED"
    response = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={})
    assert response.status_code == 409 and detail(response)["code"] == "CAMPAIGN_CREATIVE_HANDOFF_INVALIDATED"

    blocked = seed_campaign(ready=False)
    response = client.post(f"/api/v1/creatives/from-campaign/{blocked['campaign']}", json={})
    assert response.status_code == 409 and detail(response)["code"] == "CAMPAIGN_CREATIVE_HANDOFF_INVALIDATED"
    assert any(item["code"] == "PRIMARY_MESSAGE_REQUIRED" for item in detail(response)["blockers"])


@pytest.mark.parametrize("field,value,blocker", [
    ("trust_gate_snapshot", "BLOCK", "TRUST_GATE_BLOCKED"),
    ("editorial_verdict_snapshot", "NOT_RECOMMENDED", "EDITORIAL_VERDICT_NOT_ELIGIBLE"),
])
def test_current_trust_and_editorial_blockers_invalidate_handoff(client, field, value, blocker):
    ids = seed_campaign()
    with SessionLocal() as db:
        setattr(db.get(Campaign, ids["campaign"]), field, value)
        db.commit()
    response = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={})
    assert response.status_code == 409
    assert detail(response)["code"] == "CAMPAIGN_CREATIVE_HANDOFF_INVALIDATED"
    assert blocker in {item["code"] for item in detail(response)["blockers"]}


def test_financial_warning_does_not_block_and_single_enabled_channel_is_selected(client):
    ids = seed_campaign(requires_spend=True)
    state = client.get(f"/api/v1/campaigns/{ids['campaign']}/creative-handoff").json()
    assert state["state"] == "READY_TO_CREATE" and state["targetChannel"] == "TIKTOK"
    created = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={})
    assert created.status_code == 201 and created.json()["targetChannel"] == "TIKTOK"


def test_multiple_channels_require_explicit_enabled_channel(client):
    ids = seed_campaign(channels=("TIKTOK", "INSTAGRAM_REELS"))
    assert client.get(f"/api/v1/campaigns/{ids['campaign']}/creative-handoff").json()["reasonCode"] == "CREATIVE_TARGET_CHANNEL_REQUIRED"
    missing = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={})
    assert missing.status_code == 422 and detail(missing)["code"] == "CREATIVE_TARGET_CHANNEL_REQUIRED"
    chosen = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={"targetChannel": "INSTAGRAM_REELS"})
    assert chosen.status_code == 201 and chosen.json()["targetChannel"] == "INSTAGRAM_REELS"
    disabled = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={"targetChannel": "FACEBOOK_REELS"})
    assert disabled.status_code == 422 and detail(disabled)["code"] == "CREATIVE_TARGET_CHANNEL_NOT_ENABLED"


def test_experiment_validation_and_both_creation_routes_share_handoff(client):
    ids = seed_campaign()
    response = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={"experimentId": ids["experiment"]})
    assert response.status_code == 201
    body = response.json()
    assert body["experimentId"] == ids["experiment"] and body["creationKey"].endswith(f"EXPERIMENT:{ids['experiment']}")
    assert client.post(f"/api/v1/creatives/from-experiment/{ids['experiment']}", json={}).json()["id"] == body["id"]
    mismatch = client.post(f"/api/v1/creatives/from-experiment/{ids['experiment']}", json={"experimentId": "wrong"})
    assert mismatch.status_code == 422 and detail(mismatch)["code"] == "EXPERIMENT_ID_MISMATCH"
    foreign = seed_campaign()
    wrong_campaign = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={"experimentId": foreign["experiment"]})
    assert wrong_campaign.status_code == 409 and detail(wrong_campaign)["code"] == "EXPERIMENT_NOT_ELIGIBLE"


@pytest.mark.parametrize("mutation,expected", [
    ("status", "EXPERIMENT_NOT_ELIGIBLE"),
    ("angle", "EXPERIMENT_ANGLE_NOT_ELIGIBLE"),
    ("channel", "EXPERIMENT_CHANNEL_NOT_ENABLED"),
])
def test_ineligible_experiment_context_is_rejected(client, mutation, expected):
    ids = seed_campaign()
    with SessionLocal() as db:
        experiment = db.get(CampaignExperiment, ids["experiment"])
        if mutation == "status": experiment.status = "DISABLED"
        elif mutation == "angle": db.get(CampaignAngle, ids["angle"]).status = "DISABLED"
        else: experiment.target_channel = "FACEBOOK_REELS"
        db.commit()
    response = client.post(f"/api/v1/creatives/from-experiment/{ids['experiment']}", json={})
    assert response.status_code == 409 and detail(response)["code"] == expected


def test_creation_key_replay_is_read_only_and_does_not_rename_or_duplicate_log(client):
    ids = seed_campaign()
    url = f"/api/v1/creatives/from-campaign/{ids['campaign']}"
    first = client.post(url, json={"name": "Nome original"}).json()
    second = client.post(url, json={"name": "Nome diferente"}).json()
    assert second["id"] == first["id"] and second["name"] == "Nome original"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Creative).where(Creative.campaign_id == ids["campaign"])) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "CREATIVE_CREATED")) == 1


def test_experiment_keys_are_distinct_and_legacy_roots_are_reused_or_conflicted(client):
    ids = seed_campaign()
    base = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={}).json()
    experiment = client.post(f"/api/v1/creatives/from-experiment/{ids['experiment']}", json={}).json()
    assert base["id"] != experiment["id"] and base["creationKey"] != experiment["creationKey"]

    legacy = seed_campaign()
    with SessionLocal() as db:
        campaign = db.get(Campaign, legacy["campaign"])
        old = Creative(campaign_id=campaign.id, experiment_id=None, name="Legado intacto", status="DRAFT",
                       content_type="SHORT_VIDEO", target_channel="GENERIC", objective_snapshot=campaign.objective,
                       editorial_verdict_snapshot=campaign.editorial_verdict_snapshot,
                       price_verdict_snapshot=campaign.price_verdict_snapshot, disclosure_text=campaign.disclosure_text,
                       generation_mode="MANUAL")
        db.add(old)
        db.commit()
        legacy_id = old.id
    response = client.post(f"/api/v1/creatives/from-campaign/{legacy['campaign']}", json={"name": "Não renomear"})
    assert response.json()["id"] == legacy_id and response.json()["name"] == "Legado intacto"

    multiple = seed_campaign()
    with SessionLocal() as db:
        campaign = db.get(Campaign, multiple["campaign"])
        for name in ("Legado A", "Legado B"):
            db.add(Creative(campaign_id=campaign.id, name=name, status="DRAFT", content_type="SHORT_VIDEO",
                            target_channel="GENERIC", objective_snapshot=campaign.objective,
                            editorial_verdict_snapshot=campaign.editorial_verdict_snapshot,
                            price_verdict_snapshot=campaign.price_verdict_snapshot,
                            disclosure_text=campaign.disclosure_text, generation_mode="MANUAL"))
        db.commit()
    state = client.get(f"/api/v1/campaigns/{multiple['campaign']}/creative-handoff").json()
    assert state["state"] == "MULTIPLE_CREATIVES"
    response = client.post(f"/api/v1/creatives/from-campaign/{multiple['campaign']}", json={})
    assert response.status_code == 409 and detail(response)["code"] == "MULTIPLE_CREATIVES_FOR_CAMPAIGN"

    legacy_experiment = seed_campaign()
    with SessionLocal() as db:
        for name in ("Experimento legado A", "Experimento legado B"):
            db.add(Creative(campaign_id=legacy_experiment["campaign"], experiment_id=legacy_experiment["experiment"],
                            name=name, status="DRAFT", content_type="SHORT_VIDEO", target_channel="TIKTOK",
                            objective_snapshot="EDUCATION", editorial_verdict_snapshot="WORTH_IT",
                            price_verdict_snapshot="GOOD_PRICE", disclosure_text="Disclosure", generation_mode="MANUAL"))
        db.commit()
    state = client.get(f"/api/v1/campaigns/{legacy_experiment['campaign']}/creative-handoff?experimentId={legacy_experiment['experiment']}").json()
    assert state["state"] == "MULTIPLE_CREATIVES" and state["reasonCode"] == "MULTIPLE_CREATIVES_FOR_EXPERIMENT"
    response = client.post(f"/api/v1/creatives/from-experiment/{legacy_experiment['experiment']}", json={})
    assert response.status_code == 409 and detail(response)["code"] == "MULTIPLE_CREATIVES_FOR_EXPERIMENT"


def test_read_only_state_endpoint_is_repeatable_and_variants_do_not_count_as_roots(client):
    ids = seed_campaign()
    for _ in range(3):
        state = client.get(f"/api/v1/campaigns/{ids['campaign']}/creative-handoff").json()
        assert state["state"] == "READY_TO_CREATE"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DecisionLog)) == 0
        assert db.scalar(select(func.count()).select_from(Creative)) == 0
    root = client.post(f"/api/v1/creatives/from-campaign/{ids['campaign']}", json={}).json()
    with SessionLocal() as db:
        variant = Creative(campaign_id=ids["campaign"], parent_creative_id=root["id"], name="Variante", status="DRAFT",
                           content_type="SHORT_VIDEO", target_channel="TIKTOK", objective_snapshot="EDUCATION",
                           editorial_verdict_snapshot="WORTH_IT", price_verdict_snapshot="GOOD_PRICE",
                           disclosure_text="Disclosure", generation_mode="MANUAL")
        db.add(variant)
        db.commit()
    state = client.get(f"/api/v1/campaigns/{ids['campaign']}/creative-handoff").json()
    assert state["state"] == "CREATIVE_EXISTS" and state["creativeId"] == root["id"]


def test_concurrent_base_handoff_converges_to_one_creative_and_one_log():
    ids = seed_campaign()
    barrier = Barrier(2)

    def create_one(name):
        from apps.api.app.services.creative_handoff import CreativeHandoffService
        from apps.api.app.schemas import CreativeCreate
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            return CreativeHandoffService(db).create(ids["campaign"], CreativeCreate(name=name)).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create_one, ["Concorrente A", "Concorrente B"]))
    assert results[0] == results[1]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Creative).where(Creative.campaign_id == ids["campaign"])) == 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "CREATIVE_CREATED")) == 1
