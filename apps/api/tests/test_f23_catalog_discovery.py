import json

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence, RadarRun, RadarSignal
from apps.api.app.db.session import SessionLocal
from apps.api.app.integrations.mercado_livre.catalog_discovery import MercadoLivreCatalogDiscoveryService
from apps.api.app.integrations.mercado_livre.catalog_discovery_policy import BLOCKED_POLICY, catalog_discovery_eligibility
from apps.api.app.integrations.mercado_livre.catalog_discovery_relevance import catalog_discovery_relevance
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.services.assessment import CuratorAssessmentService


def query_signal(db, run, query, rank=1, source_type="TREND_GLOBAL"):
    signal = RadarSignal(radar_run_id=run.id, provider="MERCADO_LIVRE", site_id="MLB", source_type=source_type,
        source_capability="TRENDS_GLOBAL", entity_type="QUERY", display_text=query, rank=rank)
    db.add(signal); db.flush(); return signal


def product(product_id, name="Canhão De Espuma Snow Foam Pro Sigma", status="active"):
    return {"id": product_id, "name": name, "status": status, "domain_id": "MLB-CAR_WASHERS", "parent_id": "MLB1"}


def details(product_id):
    return {**product(product_id), "attributes":[{"id":"COLOR","name":"Cor","value_name":"Preto"}],
            "pictures":[{"id":"pic-1","secure_url":"https://example.test/picture.jpg","width":1200,"height":1200}]}


def client(handler):
    return MercadoLivreClient("test-token", transport=httpx.MockTransport(handler))


def test_query_creates_limited_catalog_product_candidates_and_evidence(monkeypatch):
    seen=[]
    def handler(request):
        seen.append((request.url.path, dict(request.url.params), request.headers.get("Authorization")))
        if request.url.path == "/products/search": return httpx.Response(200,json=[product("MLB73096308"),product("MLB73096309"),product("MLB73096310")])
        return httpx.Response(200,json=details(request.url.path.rsplit("/",1)[1]))
    monkeypatch.setattr(settings,"meli_catalog_discovery_limit",5)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();signal=query_signal(db,run,"canhão de espuma");db.commit()
        service=MercadoLivreCatalogDiscoveryService(db,client(handler));result=service.resolve_run(run.id)
        candidates=list(db.scalars(select(CuratorCandidate).where(CuratorCandidate.entity_type=="PRODUCT")))
        assert result["signalsProcessed"]==1 and result["productsFoundRaw"]==3 and result["productsSelected"]==3 and result["candidatesCreated"]==3
        assert {c.external_id for c in candidates}=={"MLB73096308","MLB73096309","MLB73096310"}
        assert all(c.source_radar_signal_id==signal.id and c.source_radar_run_id==run.id for c in candidates)
        evidence=list(db.scalars(select(CuratorEvidence)))
        assert {e.evidence_type for e in evidence} == {"MARKET_SIGNAL", "IDENTITY", "TECHNICAL_SPEC"}
        technical = next(e for e in evidence if e.evidence_type == "TECHNICAL_SPEC")
        assert technical.value_json["attributes"][0]["id"] == "COLOR"
        assert technical.value_json["pictures"][0]["id"] == "pic-1"
        assert seen[0][1]=={"site_id":"MLB","status":"active","q":"canhão de espuma"} and seen[0][2]=="Bearer test-token"
        assert not any(e.evidence_type=="CURRENT_PRICE" for e in evidence)
        service.close()


def test_same_catalog_product_from_two_queries_keeps_one_candidate_and_two_market_signals():
    def handler(request):
        if request.url.path=="/products/search": return httpx.Response(200,json=[product("MLB73096308")])
        return httpx.Response(200,json=details("MLB73096308"))
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();first=query_signal(db,run,"canhão de espuma",1);second=query_signal(db,run,"lavadora",3);db.commit()
        service=MercadoLivreCatalogDiscoveryService(db,client(handler));service.resolve_run(run.id)
        candidate=db.scalar(select(CuratorCandidate).where(CuratorCandidate.external_id=="MLB73096308"))
        signals=list(db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==candidate.id,CuratorEvidence.evidence_type=="MARKET_SIGNAL")))
        assert db.scalar(select(func.count()).select_from(CuratorCandidate).where(CuratorCandidate.external_id=="MLB73096308"))==1
        assert {e.source_reference for e in signals}=={first.id,second.id}
        service.resolve_run(run.id)
        assert db.scalar(select(func.count()).select_from(CuratorEvidence).where(CuratorEvidence.candidate_id==candidate.id,CuratorEvidence.evidence_type=="MARKET_SIGNAL"))==2
        service.close()


def test_catalog_only_product_has_no_commercial_item_and_is_assessable_from_market_signal():
    def handler(request):
        if request.url.path=="/products/search": return httpx.Response(200,json=[product("MLB73096308")])
        return httpx.Response(200,json=details("MLB73096308"))
    with SessionLocal() as db:
        first=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");second=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add_all([first,second]);db.flush();query_signal(db,first,"canhão de espuma",1);query_signal(db,second,"canhão de espuma",2);db.commit()
        service=MercadoLivreCatalogDiscoveryService(db,client(handler));service.resolve_run(first.id);service.resolve_run(second.id)
        candidate=db.scalar(select(CuratorCandidate).where(CuratorCandidate.external_id=="MLB73096308"))
        binding=list(db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==candidate.id,CuratorEvidence.evidence_type=="MARKETPLACE_LISTING_BINDING")))
        assessment=CuratorAssessmentService(db).assess(candidate)
        assert binding==[] and candidate.entity_type=="PRODUCT"
        assert assessment.opportunity_pillars["DEMAND_INTEREST"]["status"]=="KNOWN"
        assert assessment.opportunity_pillars["TREND_MOMENTUM"]["status"]=="KNOWN"
        assert assessment.recommendation_score is None
        service.close()


@pytest.mark.parametrize("status",[403,404,503])
def test_enrichment_failure_keeps_product_candidate_without_inventing_commercial_data(status):
    def handler(request):
        if request.url.path=="/products/search": return httpx.Response(200,json=[product("MLB73096308")])
        return httpx.Response(status,json={"error":{"code":"access_denied"}})
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();query_signal(db,run,"canhão de espuma");db.commit()
        service=MercadoLivreCatalogDiscoveryService(db,client(handler));result=service.resolve_run(run.id)
        candidate=db.scalar(select(CuratorCandidate).where(CuratorCandidate.external_id=="MLB73096308"))
        evidence=list(db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==candidate.id)))
        assert candidate and {e.evidence_type for e in evidence}=={"MARKET_SIGNAL"}
        assert not any(e.evidence_type in {"CURRENT_PRICE","PRICE_REFERENCE","SELLER_REPUTATION"} for e in evidence)
        assert result["failures"][0]["catalogProductId"]=="MLB73096308"
        service.close()


def test_limit_and_malformed_or_inactive_results_are_safe(monkeypatch):
    requested=[]
    def handler(request):
        requested.append(request.url.path)
        if request.url.path=="/products/search": return httpx.Response(200,json=[product("MLB73096308"),product("MLB73096309"),{"id":"invalid","status":"active"},product("MLB73096310",status="paused")])
        return httpx.Response(200,json=details(request.url.path.rsplit("/",1)[1]))
    monkeypatch.setattr(settings,"meli_catalog_discovery_limit",1)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();query_signal(db,run,"canhão de espuma");db.commit()
        service=MercadoLivreCatalogDiscoveryService(db,client(handler));result=service.resolve_run(run.id)
        assert result["productsFoundRaw"]==2 and result["productsSelected"]==1 and result["candidatesCreated"]==1 and requested.count("/products/MLB73096308")==1
        assert db.scalar(select(func.count()).select_from(CuratorCandidate))==1
        service.close()


def test_one_query_failure_keeps_other_query_results():
    def handler(request):
        if request.url.path=="/products/search":
            if request.url.params["q"]=="falha": return httpx.Response(503,json={"error":"temporary"})
            return httpx.Response(200,json=[product("MLB73096308")])
        return httpx.Response(200,json=details("MLB73096308"))
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();query_signal(db,run,"falha");query_signal(db,run,"canhão de espuma");db.commit()
        service=MercadoLivreCatalogDiscoveryService(db,client(handler));result=service.resolve_run(run.id)
        assert result["signalsProcessed"]==2 and result["candidatesCreated"]==1
        assert result["failures"]==[{"signalId": result["failures"][0]["signalId"], "query":"falha", "reasonCode":"PROVIDER_ERROR", "httpStatus":503}]
        service.close()


def test_market_signal_changes_opportunity_but_not_recommendation_score():
    with SessionLocal() as db:
        candidate=CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL",entity_type="PRODUCT",external_id="MLB73096308",evidence_status="SUFFICIENT_EVIDENCE",evidence_level="DATA_ANALYZED")
        db.add(candidate);db.flush()
        for evidence_type in ("TECHNICAL_SPEC","USE_CASE","POSITIVE_PATTERN","REVIEW_SUMMARY","CURRENT_PRICE","PRICE_REFERENCE","SELLER_REPUTATION","ALTERNATIVE"):
            db.add(CuratorEvidence(candidate_id=candidate.id,evidence_type=evidence_type,value_text=evidence_type,value_cents=10000 if evidence_type in {"CURRENT_PRICE","PRICE_REFERENCE"} else None,source_kind="MANUAL_OPERATOR",confidence="HIGH",verification_status="VERIFIED"))
        baseline=CuratorAssessmentService(db).assess(candidate).recommendation_score
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();signal=query_signal(db,run,"canhão de espuma")
        db.add(CuratorEvidence(candidate_id=candidate.id,evidence_type="MARKET_SIGNAL",source_kind="MERCADO_LIVRE_OFFICIAL_API",source_reference=signal.id,confidence="HIGH",verification_status="VERIFIED"));db.commit()
        assessed=CuratorAssessmentService(db).assess(candidate)
        assert assessed.recommendation_score==baseline
        assert assessed.opportunity_pillars["DEMAND_INTEREST"]["status"]=="KNOWN"


def test_discovery_logs_do_not_store_token_or_remote_payload():
    secret="token-nao-persistir"
    def handler(request):
        if request.url.path=="/products/search": return httpx.Response(200,json=[product("MLB73096308")])
        return httpx.Response(200,json={**details("MLB73096308"),"authorization":secret})
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();query_signal(db,run,"canhão de espuma");db.commit()
        service=MercadoLivreCatalogDiscoveryService(db,client(handler));service.resolve_run(run.id)
        persisted=json.dumps([e.metadata_ for e in db.scalars(select(CuratorEvidence))]+[x.metadata_ for x in db.scalars(select(__import__('apps.api.app.db.models',fromlist=['DecisionLog']).DecisionLog))])
        assert secret not in persisted and "test-token" not in persisted
        service.close()


@pytest.mark.parametrize(("query", "expected"), [
    ("snow foam", "ALLOWED"),
    ("fone de ouvido", "ALLOWED"),
    ("vape cigarro eletronico", BLOCKED_POLICY),
    ("masteron injetavel", BLOCKED_POLICY),
    ("vibrador", BLOCKED_POLICY),
    ("pistola wap", "ALLOWED"),
    ("pistola de pintura", "ALLOWED"),
    ("pistola de cola quente", "ALLOWED"),
    ("pistola pulverizadora", "ALLOWED"),
    ("pistola de silicone", "ALLOWED"),
    ("pistola 9mm", BLOCKED_POLICY),
    ("arma de fogo", BLOCKED_POLICY),
    ("rifle", BLOCKED_POLICY),
    ("revólver", BLOCKED_POLICY),
    ("espingarda", BLOCKED_POLICY),
    ("arma airsoft", BLOCKED_POLICY),
])
def test_catalog_discovery_policy_is_narrow_and_deterministic(query, expected):
    assert catalog_discovery_eligibility(query).status == expected


def test_policy_blocked_query_never_calls_catalog_api_or_creates_candidate():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(500)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();signal=query_signal(db,run,"vape cigarro eletronico");db.commit()
        service=MercadoLivreCatalogDiscoveryService(db,client(handler));result=service.resolve_run(run.id)
        assert calls == [] and result["failures"] == []
        assert result["policyBlockedCount"] == 1
        assert result["policyBlocked"] == [{"signalId": signal.id, "query": "vape cigarro eletronico", "status": BLOCKED_POLICY, "reasonCode": "RESTRICTED_PRODUCT_CATEGORY"}]
        assert db.scalar(select(func.count()).select_from(CuratorCandidate)) == 0
        service.close()


def test_mixed_batch_skips_policy_blocked_query_and_processes_allowed_query():
    calls = []
    def handler(request):
        calls.append((request.url.path, request.url.params.get("q")))
        if request.url.path == "/products/search": return httpx.Response(200, json=[product("MLB73096308")])
        return httpx.Response(200, json=details("MLB73096308"))
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();query_signal(db,run,"vibrador");query_signal(db,run,"snow foam",2);db.commit()
        service=MercadoLivreCatalogDiscoveryService(db,client(handler));result=service.resolve_run(run.id)
        assert result["policyBlockedCount"] == 1 and result["candidatesCreated"] == 1
        assert [call for call in calls if call[0] == "/products/search"] == [("/products/search", "snow foam")]
        assert db.scalar(select(func.count()).select_from(CuratorCandidate)) == 1
        service.close()


def test_run_limits_allowed_queries_and_reports_unprocessed_signals(monkeypatch):
    searches = []
    def handler(request):
        if request.url.path == "/products/search":
            searches.append(request.url.params["q"])
            return httpx.Response(200, json=[])
        raise AssertionError("Unexpected catalog enrichment")
    monkeypatch.setattr(settings, "meli_catalog_discovery_max_signals_per_run", 20)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush()
        for rank in range(1, 31): query_signal(db, run, f"produto {rank}", rank)
        db.commit()
        service=MercadoLivreCatalogDiscoveryService(db, client(handler));result=service.resolve_run(run.id)
        assert result["signalsAvailable"] == 30 and result["signalsEligible"] == 30
        assert result["signalsProcessed"] == 20 and result["signalsSkippedByLimit"] == 10
        assert searches == [f"produto {rank}" for rank in range(1, 21)]
        assert db.scalar(select(func.count()).select_from(CuratorCandidate)) == 0
        service.close()


def test_policy_blocked_queries_do_not_consume_per_run_signal_limit(monkeypatch):
    searches = []
    def handler(request):
        if request.url.path == "/products/search":
            searches.append(request.url.params["q"])
            return httpx.Response(200, json=[])
        raise AssertionError("Unexpected catalog enrichment")
    monkeypatch.setattr(settings, "meli_catalog_discovery_max_signals_per_run", 20)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush()
        for rank in range(1, 11): query_signal(db, run, f"vape {rank}", rank)
        for rank in range(11, 36): query_signal(db, run, f"produto {rank}", rank)
        db.commit()
        service=MercadoLivreCatalogDiscoveryService(db, client(handler));result=service.resolve_run(run.id)
        assert result["policyBlockedCount"] == 10 and result["signalsEligible"] == 25
        assert result["signalsProcessed"] == 20 and result["signalsSkippedByLimit"] == 5
        assert searches == [f"produto {rank}" for rank in range(11, 31)]
        assert db.scalar(select(func.count()).select_from(CuratorCandidate)) == 0
        service.close()


def test_categorized_run_prioritizes_category_trends_before_global(monkeypatch):
    searches = []
    def handler(request):
        if request.url.path == "/products/search":
            searches.append(request.url.params["q"])
            return httpx.Response(200, json=[])
        raise AssertionError("Unexpected catalog enrichment")
    monkeypatch.setattr(settings, "meli_catalog_discovery_max_signals_per_run", 2)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED",requested_category_id="MLB123");db.add(run);db.flush()
        query_signal(db, run, "global rank um", 1, "TREND_GLOBAL")
        query_signal(db, run, "categoria rank dois", 2, "TREND_CATEGORY")
        query_signal(db, run, "categoria rank tres", 3, "TREND_CATEGORY")
        db.commit()
        service=MercadoLivreCatalogDiscoveryService(db, client(handler));service.resolve_run(run.id)
        assert searches == ["categoria rank dois", "categoria rank tres"]
        service.close()


def test_uncategorized_run_order_is_deterministic_by_rank_then_source(monkeypatch):
    searches = []
    def handler(request):
        if request.url.path == "/products/search":
            searches.append(request.url.params["q"])
            return httpx.Response(200, json=[])
        raise AssertionError("Unexpected catalog enrichment")
    monkeypatch.setattr(settings, "meli_catalog_discovery_max_signals_per_run", 3)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush()
        query_signal(db, run, "global rank dois", 2, "TREND_GLOBAL")
        query_signal(db, run, "categoria rank um", 1, "TREND_CATEGORY")
        query_signal(db, run, "global rank um", 1, "TREND_GLOBAL")
        db.commit()
        service=MercadoLivreCatalogDiscoveryService(db, client(handler));service.resolve_run(run.id)
        assert searches == ["categoria rank um", "global rank um", "global rank dois"]
        service.close()


def test_catalog_evidence_is_aggregated_and_reruns_are_idempotent():
    def handler(request):
        if request.url.path == "/products/search": return httpx.Response(200, json=[product("MLB73096308")])
        return httpx.Response(200, json=details("MLB73096308"))
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush()
        first=query_signal(db, run, "snow foam", 1);second=query_signal(db, run, "canhão de espuma", 2);db.commit()
        service=MercadoLivreCatalogDiscoveryService(db, client(handler));first_result=service.resolve_run(run.id)
        candidate=db.scalar(select(CuratorCandidate).where(CuratorCandidate.external_id == "MLB73096308"))
        evidence=list(db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id == candidate.id)))
        assert {item.evidence_type for item in evidence} == {"MARKET_SIGNAL", "IDENTITY", "TECHNICAL_SPEC"}
        assert {item.source_reference for item in evidence if item.evidence_type == "MARKET_SIGNAL"} == {first.id, second.id}
        assert first_result["evidenceAdded"] == 4
        count_before=len(evidence)
        second_result=service.resolve_run(run.id)
        assert len(list(db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id == candidate.id)))) == count_before
        assert second_result["evidenceAdded"] == 0
        service.close()


def test_products_selected_never_exceeds_processed_queries_times_per_query_limit(monkeypatch):
    def handler(request):
        if request.url.path == "/products/search":
            offset = 0 if request.url.params["q"] == "produto 1" else 10
            return httpx.Response(200, json=[product(f"MLB730963{offset + index}") for index in range(8)])
        return httpx.Response(200, json=details(request.url.path.rsplit("/", 1)[1]))
    monkeypatch.setattr(settings, "meli_catalog_discovery_limit", 5)
    monkeypatch.setattr(settings, "meli_catalog_discovery_max_signals_per_run", 2)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush()
        for rank in range(1, 4): query_signal(db, run, f"produto {rank}", rank)
        db.commit()
        service=MercadoLivreCatalogDiscoveryService(db, client(handler));result=service.resolve_run(run.id)
        assert result["productsFoundRaw"] == 16
        assert result["productsSelected"] == 10
        assert result["productsSelected"] <= result["signalsProcessed"] * settings.meli_catalog_discovery_limit
        assert db.scalar(select(func.count()).select_from(CuratorCandidate)) == 10
        service.close()


def test_relevance_ranks_primary_product_above_generic_accessories_and_reports_selection():
    primary_id = "MLB73096402"
    search_results = [
        product("MLB73096401", "Adaptador Niple Snow Foam"),
        product(primary_id, "Canhão de Espuma Snow Foam Pro"),
        product("MLB73096403", "Conector Snow Foam"),
        product("MLB73096404", "Borrifador Snow Foam"),
    ]
    def handler(request):
        if request.url.path == "/products/search": return httpx.Response(200, json=search_results)
        return httpx.Response(200, json=details(request.url.path.rsplit("/", 1)[1]))
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();query_signal(db,run,"snow foam");db.commit()
        service=MercadoLivreCatalogDiscoveryService(db, client(handler));result=service.resolve_run(run.id)
        selected=result["selectedProducts"][0]["selectedProducts"]
        assert selected[0]["catalogProductId"] == primary_id
        assert "ACCESSORY_PENALTY" not in selected[0]["reasons"]
        assert all("ACCESSORY_PENALTY" in item["reasons"] for item in selected[1:])
        service.close()


def test_accessory_terms_are_not_penalized_when_they_are_part_of_query():
    adapter = catalog_discovery_relevance("adaptador starlink", "Adaptador Starlink Mini")
    cable = catalog_discovery_relevance("cabo usb c", "Cabo USB C 2m")
    assert "ACCESSORY_PENALTY" not in adapter.reasons
    assert "ACCESSORY_PENALTY" not in cable.reasons


def test_relevance_score_and_tiebreak_are_deterministic():
    assert catalog_discovery_relevance("fone de ouvido", "Fone de Ouvido Bluetooth").score == catalog_discovery_relevance("fone de ouvido", "Fone de Ouvido Bluetooth").score
    with SessionLocal() as db:
        service=MercadoLivreCatalogDiscoveryService(db, client(lambda request: httpx.Response(500)))
        ranked=service._rank_products("fone", [product("MLB73096410", "Fone"), product("MLB73096409", "Fone")])
        assert [item["product"]["id"] for item in ranked] == ["MLB73096410", "MLB73096409"]
        service.close()


def test_top_five_is_applied_after_relevance_ranking(monkeypatch):
    primary_id = "MLB73096499"
    results = [product(f"MLB730964{index}", f"Adaptador Snow Foam {index}") for index in range(1, 7)] + [product(primary_id, "Canhão de Espuma Snow Foam")]
    requested = []
    def handler(request):
        requested.append(request.url.path)
        if request.url.path == "/products/search": return httpx.Response(200, json=results)
        return httpx.Response(200, json=details(request.url.path.rsplit("/", 1)[1]))
    monkeypatch.setattr(settings, "meli_catalog_discovery_limit", 5)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();query_signal(db,run,"snow foam");db.commit()
        service=MercadoLivreCatalogDiscoveryService(db, client(handler));result=service.resolve_run(run.id)
        ids=[item["catalogProductId"] for item in result["selectedProducts"][0]["selectedProducts"]]
        assert result["productsFoundRaw"] == 7 and result["productsSelected"] == 5
        assert primary_id in ids and f"/products/{primary_id}" in requested
        assert db.scalar(select(func.count()).select_from(CuratorCandidate)) == 5
        service.close()


def test_existing_manual_product_candidate_is_reused_and_receives_market_signal():
    catalog_id = "MLB73096501"
    def handler(request):
        if request.url.path == "/products/search": return httpx.Response(200, json=[product(catalog_id, "Fone de Ouvido")])
        return httpx.Response(200, json=details(catalog_id))
    with SessionLocal() as db:
        existing=CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL",entity_type="PRODUCT",external_id=catalog_id,working_title="Manual")
        db.add(existing);db.flush()
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();signal=query_signal(db,run,"fone de ouvido");db.commit()
        service=MercadoLivreCatalogDiscoveryService(db, client(handler));result=service.resolve_run(run.id)
        assert result["candidatesCreated"] == 0 and result["candidatesReused"] == 1
        assert db.scalar(select(func.count()).select_from(CuratorCandidate).where(CuratorCandidate.external_id == catalog_id)) == 1
        assert db.scalar(select(func.count()).select_from(CuratorEvidence).where(CuratorEvidence.candidate_id == existing.id, CuratorEvidence.evidence_type == "MARKET_SIGNAL", CuratorEvidence.source_reference == signal.id)) == 1
        service.close()
