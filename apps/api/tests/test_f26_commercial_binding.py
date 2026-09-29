import httpx
import pytest
from sqlalchemy import select

from apps.api.app.db.models import CuratorCandidate, CuratorEvidence, DecisionLog
from apps.api.app.db.session import SessionLocal
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.services.commercial_binding import CommercialBindingService
from apps.api.app.services.evidence_enrichment import CandidateEvidenceEnrichmentService
from apps.api.tests.test_f25_evidence_enrichment import setup


def meli(handler):
    return MercadoLivreClient("test-token", transport=httpx.MockTransport(handler))


def candidate(db):
    row = CuratorCandidate(provider="MERCADO_LIVRE", site_id="MLB", source_type="CATALOG_DISCOVERY",
                           entity_type="PRODUCT", external_id="MLB11111111", working_title="Produto")
    db.add(row)
    db.commit()
    return row


def test_explicit_item_and_urls_are_bound_without_changing_catalog_identity():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"title": "Oferta", "catalog_product_id": "MLB11111111",
                                         "seller_id": 42, "price": 129.9, "currency_id": "BRL",
                                         "available_quantity": 3, "permalink": "https://example.test/item",
                                         "status": "active", "condition": "new"})

    with SessionLocal() as db:
        row = candidate(db)
        service = CommercialBindingService(db, meli(handler))
        result = service.bind(row.id, "https://www.mercadolivre.com.br/produto/p/MLB11111111?wid=MLB22222222")
        assert result["catalogProductId"] == "MLB11111111"
        assert result["sourceItemId"] == "MLB22222222"
        assert result["validationStatus"] == "VALIDATED"
        assert result["catalogMatchStatus"] == "MATCHED"
        assert db.get(CuratorCandidate, row.id).external_id == "MLB11111111"
        assert calls == ["/items/MLB22222222"]
        service.close()


@pytest.mark.parametrize("source", ["MLB22222222", "https://produto.mercadolivre.com.br/MLB-22222222-oferta.html"])
def test_direct_item_sources_are_accepted(source):
    def handler(request):
        return httpx.Response(200, json={"catalog_product_id": "MLB11111111"})

    with SessionLocal() as db:
        row = candidate(db)
        service = CommercialBindingService(db, meli(handler))
        assert service.bind(row.id, source)["sourceItemId"] == "MLB22222222"
        service.close()


def test_catalog_only_url_does_not_create_incomplete_offer():
    with SessionLocal() as db:
        row = candidate(db)
        service = CommercialBindingService(db, meli(lambda request: pytest.fail("No remote request expected")))
        with pytest.raises(ValueError, match="CATALOG_PRODUCT_WITHOUT_OFFER"):
            service.bind(row.id, "https://www.mercadolivre.com.br/produto/p/MLB11111111")
        assert service.current(row.id)["sourceItemId"] is None
        service.close()


@pytest.mark.parametrize(("status", "expected", "reason"), [(403, "UNVERIFIED", "FORBIDDEN"), (404, "INVALID", "NOT_FOUND")])
def test_forbidden_or_missing_item_keeps_safe_binding_status(status, expected, reason):
    with SessionLocal() as db:
        row = candidate(db)
        service = CommercialBindingService(db, meli(lambda request: httpx.Response(status, json={"error": "access_denied"})))
        result = service.bind(row.id, "MLB22222222")
        assert result["sourceItemId"] == "MLB22222222"
        assert result["validationStatus"] == expected
        assert result["validationReasonCode"] == reason
        service.close()


def test_catalog_mismatch_requires_explicit_confirmation_and_is_audited():
    def handler(request):
        return httpx.Response(200, json={"catalog_product_id": "MLB99999999"})

    with SessionLocal() as db:
        row = candidate(db)
        service = CommercialBindingService(db, meli(handler))
        with pytest.raises(ValueError, match="CATALOG_PRODUCT_MISMATCH_CONFIRMATION_REQUIRED"):
            service.bind(row.id, "MLB22222222")
        assert service.current(row.id)["sourceItemId"] is None
        result = service.bind(row.id, "MLB22222222", confirm_mismatch=True)
        assert result["catalogMatchStatus"] == "MISMATCH"
        assert db.scalar(select(DecisionLog).where(DecisionLog.action == "COMMERCIAL_BINDING_MISMATCH"))
        service.close()


def test_manual_affiliate_url_is_format_only_and_never_replaced_silently():
    with SessionLocal() as db:
        row = candidate(db)
        service = CommercialBindingService(db, meli(lambda request: pytest.fail("Affiliate URLs are not resolved remotely")))
        first = service.set_affiliate_url(row.id, "https://affiliate.example/path")
        assert first["affiliate"] == {"status": "FORMAT_VALID", "urlPresent": True, "url": "https://affiliate.example/path"}
        with pytest.raises(ValueError, match="AFFILIATE_URL_REPLACEMENT_CONFIRMATION_REQUIRED"):
            service.set_affiliate_url(row.id, "https://affiliate.example/other")
        assert service.set_affiliate_url(row.id, "https://affiliate.example/other", confirm_replace=True)["affiliate"]["url"] == "https://affiliate.example/other"
        service.close()


def test_legacy_forbidden_binding_is_presented_as_unverified_without_removal():
    with SessionLocal() as db:
        row = candidate(db)
        db.add(CuratorEvidence(candidate_id=row.id, evidence_type="MARKETPLACE_LISTING_BINDING",
                               value_json={"catalogProductId": row.external_id, "sourceItemId": "MLB22222222",
                                           "itemDetailsStatus": "FORBIDDEN"}, source_kind="MANUAL_OPERATOR",
                               confidence="HIGH", verification_status="UNVERIFIED"))
        db.commit()
        service = CommercialBindingService(db, meli(lambda request: pytest.fail("Current state needs no request")))
        result = service.current(row.id)
        assert result["sourceItemId"] == "MLB22222222"
        assert result["validationStatus"] == "UNVERIFIED"
        assert result["validationReasonCode"] == "FORBIDDEN"
        service.close()


def test_remove_binding_closes_only_its_active_commercial_evidence_and_keeps_history():
    with SessionLocal() as db:
        row = candidate(db)
        source_item = "MLB849301960"
        db.add(CuratorEvidence(candidate_id=row.id, evidence_type="MARKETPLACE_LISTING_BINDING",
                               value_json={"catalogProductId": row.external_id, "sourceItemId": source_item,
                                           "observed": {"sellerId": "44203679"}}, source_kind="MANUAL_OPERATOR",
                               confidence="HIGH", verification_status="VERIFIED"))
        related = [
            CuratorEvidence(candidate_id=row.id, evidence_type="CURRENT_PRICE", value_json={"observedItemId": source_item, "catalogProductId": "MLB59889796", "currency": "BRL", "amount": 149}, source_kind="MERCADO_LIVRE_OFFICIAL_API", source_reference="enrichment:CURRENT_PRICE:legacy", confidence="HIGH", verification_status="VERIFIED"),
            CuratorEvidence(candidate_id=row.id, evidence_type="REVIEW_SUMMARY", value_json={"itemId": source_item, "catalogProductId": "MLB59889796", "ratingAverage": 0, "totalReviews": 0}, source_kind="MERCADO_LIVRE_OFFICIAL_API", source_reference="enrichment:REVIEW_SUMMARY:legacy", confidence="HIGH", verification_status="VERIFIED"),
            CuratorEvidence(candidate_id=row.id, evidence_type="SELLER_REPUTATION", value_json={"sellerId": "44203679", "sellerReputation": {"level_id": "5_green"}}, source_kind="MERCADO_LIVRE_OFFICIAL_API", source_reference="enrichment:SELLER_REPUTATION:legacy", confidence="HIGH", verification_status="VERIFIED"),
        ]
        untouched = [
            CuratorEvidence(candidate_id=row.id, evidence_type="IDENTITY", value_text="Produto", source_kind="MERCADO_LIVRE_OFFICIAL_API", source_reference="catalog", confidence="HIGH", verification_status="VERIFIED"),
            CuratorEvidence(candidate_id=row.id, evidence_type="TECHNICAL_SPEC", value_json={"attributes": []}, source_kind="MERCADO_LIVRE_OFFICIAL_API", source_reference="catalog:technical", confidence="HIGH", verification_status="VERIFIED"),
            CuratorEvidence(candidate_id=row.id, evidence_type="CURRENT_PRICE", value_json={"observedItemId": "MLBOTHER"}, source_kind="MERCADO_LIVRE_OFFICIAL_API", source_reference="enrichment:CURRENT_PRICE:other", confidence="HIGH", verification_status="VERIFIED"),
        ]
        db.add_all(related + untouched)
        db.commit()
        service = CommercialBindingService(db, meli(lambda request: pytest.fail("Removal does not call Mercado Livre")))
        service.remove(row.id)
        assert service.current(row.id)["sourceItemId"] is None
        assert all(evidence.valid_until is not None for evidence in related)
        assert all(evidence.valid_until is None for evidence in untouched)
        assert db.scalar(select(DecisionLog).where(DecisionLog.action == "COMMERCIAL_BINDING_REMOVED").order_by(DecisionLog.timestamp.desc())).metadata_["commercialEvidenceClosedCount"] == 3
        service.close()


def test_remove_binding_closes_new_provenance_without_closing_another_offer():
    with SessionLocal() as db:
        row = candidate(db)
        source_item = "MLB849301960"
        db.add(CuratorEvidence(candidate_id=row.id, evidence_type="MARKETPLACE_LISTING_BINDING",
                               value_json={"sourceItemId": source_item, "observed": {"sellerId": "44203679"}},
                               source_kind="MANUAL_OPERATOR", confidence="HIGH", verification_status="VERIFIED"))
        bound = CuratorEvidence(candidate_id=row.id, evidence_type="SELLER_REPUTATION",
                                value_json={"sellerId": "44203679"}, source_kind="MERCADO_LIVRE_OFFICIAL_API",
                                source_reference="enrichment:SELLER_REPUTATION:new", confidence="HIGH",
                                verification_status="VERIFIED",
                                metadata_={"sourceItemId": source_item, "commercialSource": "EXPLICIT_BINDING"})
        other = CuratorEvidence(candidate_id=row.id, evidence_type="CURRENT_PRICE",
                                value_json={"observedItemId": "MLB4759377111"}, source_kind="MERCADO_LIVRE_OFFICIAL_API",
                                source_reference="enrichment:CURRENT_PRICE:other", confidence="HIGH",
                                verification_status="VERIFIED",
                                metadata_={"sourceItemId": "MLB4759377111", "commercialSource": "EXPLICIT_BINDING"})
        db.add_all((bound, other))
        db.commit()
        service = CommercialBindingService(db, meli(lambda request: pytest.fail("Removal does not call Mercado Livre")))
        service.remove(row.id)
        assert bound.valid_until is not None
        assert other.valid_until is None
        service.close()


def test_enrichment_prefers_explicit_item_and_a_forbidden_item_does_not_fail_batch():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.startswith("/products/"):
            return httpx.Response(200, json={"buy_box_winner": {"item_id": "MLBBUYBOX", "seller_id": 1}})
        if request.url.path == "/items/MLBEXPLICIT":
            return httpx.Response(403, json={"error": "access_denied"})
        return httpx.Response(500)

    with SessionLocal() as db:
        run, row = setup(db)
        db.add(CuratorEvidence(candidate_id=row.id, evidence_type="MARKETPLACE_LISTING_BINDING",
                               value_json={"catalogProductId": row.external_id, "sourceItemId": "MLBEXPLICIT"},
                               source_kind="MANUAL_OPERATOR", confidence="HIGH", verification_status="UNVERIFIED"))
        db.commit()
        service = CandidateEvidenceEnrichmentService(db, meli(handler))
        output = service.enrich_run(run.id)["candidates"][0]
        assert output["observedItemId"] == "MLBEXPLICIT"
        assert output["sourceStatuses"]["price"]["status"] == "FORBIDDEN"
        assert output["sourceStatuses"]["reviews"]["status"] == "FORBIDDEN"
        assert "/items/MLBEXPLICIT" in calls
        assert "/items/MLBBUYBOX" not in calls
        service.close()


@pytest.mark.parametrize("item_status", [200, 403])
def test_individual_enrichment_works_without_radar_run_and_preserves_binding(item_status):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.startswith("/products/"):
            return httpx.Response(200, json={"buy_box_winner": None})
        if request.url.path == "/items/MLB4759377111":
            if item_status == 403:
                return httpx.Response(403, json={"error": "access_denied"})
            return httpx.Response(200, json={"seller_id": 42, "price": 129.9, "currency_id": "BRL"})
        if request.url.path.startswith("/reviews/"):
            return httpx.Response(200, json={"paging": {"total": 0}, "reviews": []})
        return httpx.Response(200, json={"seller_reputation": {"level_id": "5_green"}})

    with SessionLocal() as db:
        row = candidate(db)
        db.add(CuratorEvidence(candidate_id=row.id, evidence_type="MARKETPLACE_LISTING_BINDING",
                               value_json={"catalogProductId": row.external_id, "sourceItemId": "MLB4759377111"},
                               source_kind="MANUAL_OPERATOR", confidence="HIGH", verification_status="UNVERIFIED"))
        db.commit()
        service = CandidateEvidenceEnrichmentService(db, meli(handler))
        result = service.enrich_candidate(row.id)
        assert result["candidateId"] == row.id
        assert result["observedItemId"] == "MLB4759377111"
        assert "/items/MLB4759377111" in calls
        if item_status == 403:
            assert result["sourceStatuses"]["price"]["status"] == "FORBIDDEN"
            assert db.scalar(select(CuratorEvidence).where(CuratorEvidence.candidate_id == row.id,
                             CuratorEvidence.evidence_type == "MARKETPLACE_LISTING_BINDING")) is not None
        else:
            assert result["commercialEvidenceAvailable"] is True
            snapshots = list(db.scalars(select(CuratorEvidence).where(
                CuratorEvidence.candidate_id == row.id,
                CuratorEvidence.evidence_type.in_(("CURRENT_PRICE", "REVIEW_SUMMARY", "SELLER_REPUTATION")),
            )))
            assert snapshots
            assert all((snapshot.metadata_ or {}).get("sourceItemId") == "MLB4759377111" for snapshot in snapshots)
            assert all((snapshot.metadata_ or {}).get("commercialSource") == "EXPLICIT_BINDING" for snapshot in snapshots)
        service.close()
