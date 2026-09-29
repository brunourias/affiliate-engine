from apps.api.app.integrations.mercado_livre.diagnostics import parse_item_id, parse_item_reference
from apps.api.app.integrations.mercado_livre.models import CapabilityResult
from apps.api.app.db.models import Campaign, Creative, CuratorAssessment, CuratorCandidate, CuratorEvidence, DecisionLog, MarketplaceCapability
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.mercado_livre_commercial import AffiliateDestinationValidator, MarketplaceListingBindingService, MarketplaceRefreshService
from apps.api.app.services.commercial_snapshot import MarketplaceCommercialSnapshotService
from sqlalchemy import func, select


def test_binding_accepts_official_item_url_and_id_only():
    assert parse_item_id("MLB123456789") == "MLB123456789"
    assert parse_item_id("https://www.mercadolivre.com.br/p/MLB123456789") is None
    assert parse_item_id("https://example.com/MLB123456789") is None
    assert parse_item_id("https://www.mercadolivre.com.br/ofertas") is None


def test_catalog_url_without_wid_uses_catalog_reference_as_fallback():
    result=parse_item_reference("https://www.mercadolivre.com.br/camera/p/MLB47535705")
    assert (result.source_item_id,result.catalog_product_id,result.resolution_method)==(None,"MLB47535705","CATALOG_PRODUCT_PATH")


def test_catalog_url_prioritizes_valid_wid_and_preserves_catalog_id():
    result=parse_item_reference("https://www.mercadolivre.com.br/camera/p/MLB47535705#origin=share&wid=MLB6167651244&sid=share")
    assert (result.item_id,result.catalog_product_id,result.resolution_method)==("MLB6167651244","MLB47535705","WID_COMMERCIAL_OFFER")


def test_invalid_or_wrong_site_wid_is_ignored_safely():
    assert parse_item_reference("https://www.mercadolivre.com.br/camera/p/MLB47535705?wid=INVALID").item_id is None
    assert parse_item_reference("https://www.mercadolivre.com.br/camera/p/MLB47535705?wid=MLA6167651244").item_id is None
    assert parse_item_reference("https://example.com/camera/p/MLB47535705?wid=MLB6167651244").item_id is None


def test_direct_item_url_keeps_existing_behavior():
    result=parse_item_reference("https://produto.mercadolivre.com.br/MLB-6167651244-camera-_JM")
    assert (result.item_id,result.catalog_product_id,result.resolution_method)==("MLB6167651244",None,"DIRECT_ITEM_PATH")


def test_binding_keeps_original_permalink_and_catalog_separately():
    source="https://www.mercadolivre.com.br/camera/p/MLB47535705#origin=share&wid=MLB6167651244"
    with SessionLocal() as db:
        row=CuratorCandidate(provider="OTHER",site_id=None,source_type="MANUAL",entity_type="MANUAL")
        db.add(row);db.commit();result=MarketplaceListingBindingService(db).bind(row.id,source)
        evidence=db.scalar(select(CuratorEvidence).where(CuratorEvidence.evidence_type=="MARKETPLACE_LISTING_BINDING"))
        assert result["itemId"]==result["sourceItemId"]=="MLB6167651244" and result["catalogProductId"]=="MLB47535705"
        assert result["externalId"]=="MLB47535705" and result["entityType"]=="PRODUCT"
        assert result["sourcePermalink"]==source
        assert evidence.value_json["sourceItemId"]=="MLB6167651244" and evidence.value_json["catalogProductId"]=="MLB47535705"


def test_affiliate_destination_requires_same_item_and_never_invents_url():
    assert AffiliateDestinationValidator.validate(None, "MLB123456789")["status"] == "UNKNOWN"
    assert AffiliateDestinationValidator.validate("https://www.mercadolivre.com.br/MLB123456789", "MLB123456789")["status"] == "UNKNOWN"
    assert AffiliateDestinationValidator.validate("https://www.mercadolivre.com.br/MLB123456789", "MLB123456789", official=True, strategy="DIRECT_AFFILIATE_LINK", destination_url="https://www.mercadolivre.com.br/MLB123456789")["status"] == "READY"
    assert AffiliateDestinationValidator.validate("https://www.mercadolivre.com.br/MLB987654321", "MLB123456789")["status"] == "UNKNOWN"
    assert AffiliateDestinationValidator.validate("https://www.mercadolivre.com.br", "MLB123456789")["status"] == "UNKNOWN"


def test_official_payload_text_is_utf8_safe():
    value = "Parafusadeira doméstica: ação, potência, precisão e fácil"
    assert value.encode("utf-8").decode("utf-8") == value


class FakeClient:
    def __init__(self, payloads): self.payloads = list(payloads); self.calls = []
    def get(self, key, endpoint, **kwargs):
        self.calls.append((key, endpoint, kwargs))
        data = self.payloads.pop(0)
        return CapabilityResult(key, "AVAILABLE", endpoint, 200, data=data)


class CapabilityFakeClient:
    def __init__(self,responses):self.responses=responses;self.calls=[]
    def get(self,key,endpoint,**kwargs):
        self.calls.append((key,endpoint,kwargs));return self.responses[key]


def _catalog_candidate(db,item_status="FORBIDDEN"):
    source="https://www.mercadolivre.com.br/snow-foam/p/MLB73096308?wid=MLB4759377111"
    candidate=CuratorCandidate(provider="OTHER",site_id=None,source_type="MANUAL",entity_type="MANUAL")
    db.add(candidate);db.commit();MarketplaceListingBindingService(db).bind(candidate.id,source)
    db.add(MarketplaceCapability(provider="MERCADO_LIVRE",capability_key="ITEM_DETAILS",status=item_status,metadata_={
        "itemProbes":{"MLB4759377111":{"status":item_status,"httpStatus":403 if item_status=="FORBIDDEN" else 200,
                                         "reasonCode":"HTTP_403" if item_status=="FORBIDDEN" else "HTTP_200"}}}))
    db.commit();return candidate


def test_catalog_available_keeps_product_when_source_item_is_forbidden_without_commercial_inference():
    catalog={"id":"MLB73096308","name":"Canhão De Espuma Snow Foam Pro Sigma","status":"active",
             "domain_id":"MLB-VEHICLE_SHAMPOOS","parent_id":"MLB73096307","attributes":[],"pictures":[]}
    fake=CapabilityFakeClient({"CATALOG_PRODUCT":CapabilityResult("CATALOG_PRODUCT","AVAILABLE","/products/MLB73096308",200,data=catalog)})
    with SessionLocal() as db:
        candidate=_catalog_candidate(db)
        result=MarketplaceRefreshService(db,fake).refresh(candidate.id)
        db.refresh(candidate)
        assert candidate.external_id=="MLB73096308" and candidate.entity_type=="PRODUCT"
        assert result["catalogProductStatus"]=="AVAILABLE" and result["itemDetailsStatus"]=="FORBIDDEN"
        assert result["commercialCompleteness"]=="UNAVAILABLE"
        assert result["price"] is None and result["originalPrice"] is None and result["currency"] is None
        assert result["title"]=="Canhão De Espuma Snow Foam Pro Sigma"
        assert fake.calls==[("CATALOG_PRODUCT","/products/MLB73096308",{"requires_auth":True})]
        binding=db.scalar(select(CuratorEvidence).where(CuratorEvidence.evidence_type=="MARKETPLACE_LISTING_BINDING"))
        assert binding.value_json["sourceItemId"]=="MLB4759377111" and binding.value_json["catalogProductId"]=="MLB73096308"
        assert binding.value_json["commercialCompleteness"]=="UNAVAILABLE"
        assessment=CuratorAssessment(candidate_id=candidate.id,assessment_version=1,evidence_status="PARTIAL",evidence_level="PUBLIC_VERIFIED",trust_gate="WARN",trust_reasons=[],trust_warnings=[],recommendation_coverage_percent=0,opportunity_coverage_percent=0,price_verdict="UNKNOWN",editorial_verdict="NEEDS_MORE_EVIDENCE",recommendation_pillars={},opportunity_pillars={},evidence_ids_used=[],unknown_fields=[],rationale={})
        db.add(assessment);db.flush()
        campaign=Campaign(candidate_id=candidate.id,assessment_id=assessment.id,name="Snow Foam",status="DRAFT",objective="EDUCATION",editorial_verdict_snapshot="NEEDS_MORE_EVIDENCE",trust_gate_snapshot="WARN",price_verdict_snapshot="UNKNOWN",campaign_priority="MEDIUM",disclosure_text="Link de afiliado",trust_warnings_snapshot=[],required_disclosures=[],required_warnings=[],forbidden_claims=[])
        db.add(campaign);db.flush()
        creative=Creative(campaign_id=campaign.id,name="Snow Foam",status="DRAFT",content_type="STATIC_POST",target_channel="GENERIC",objective_snapshot="EDUCATION",editorial_verdict_snapshot="NEEDS_MORE_EVIDENCE",price_verdict_snapshot="UNKNOWN",disclosure_text="Link de afiliado",required_warnings=[],forbidden_claims=[])
        db.add(creative);db.commit()
        snapshot=MarketplaceCommercialSnapshotService(db).build(creative.id)
        assert snapshot["catalogProductId"]=="MLB73096308" and snapshot["sourceItemId"]=="MLB4759377111"
        assert snapshot["commercialCompleteness"]=="UNAVAILABLE"
        assert snapshot["pricing"]["status"]=="UNKNOWN" and snapshot["pricing"]["currentPrice"] is None
        assert snapshot["inventory"]=={"status":"UNKNOWN","availableQuantity":None}
        assert snapshot["seller"]=={"status":"UNKNOWN","id":None,"reputation":None}
        assert snapshot["logistics"]["status"]=="UNKNOWN" and snapshot["socialProof"]["status"]=="UNKNOWN"
        assert snapshot["socialProof"]["soldQuantity"] is None


def test_catalog_and_source_item_can_both_be_available_independently():
    catalog={"id":"MLB73096308","name":"Snow Foam","status":"active"}
    item={"id":"MLB4759377111","title":"Oferta Snow Foam","price":199.9,"currency_id":"BRL","pictures":[],"attributes":[]}
    fake=CapabilityFakeClient({
        "CATALOG_PRODUCT":CapabilityResult("CATALOG_PRODUCT","AVAILABLE","/products/MLB73096308",200,data=catalog),
        "ITEM_DETAILS":CapabilityResult("ITEM_DETAILS","AVAILABLE","/items/MLB4759377111",200,data=item),
    })
    with SessionLocal() as db:
        candidate=_catalog_candidate(db,"AVAILABLE")
        result=MarketplaceRefreshService(db,fake).refresh(candidate.id)
        assert result["catalogProductStatus"]==result["itemDetailsStatus"]=="AVAILABLE"
        assert result["commercialCompleteness"]=="AVAILABLE" and result["price"]==199.9
        assert {call[0] for call in fake.calls}=={"CATALOG_PRODUCT","ITEM_DETAILS"}


def test_unavailable_catalog_and_forbidden_item_leave_product_unavailable_without_invented_data():
    fake=CapabilityFakeClient({"CATALOG_PRODUCT":CapabilityResult("CATALOG_PRODUCT","NOT_SUPPORTED","/products/MLB73096308",404,reason_code="HTTP_404")})
    with SessionLocal() as db:
        candidate=_catalog_candidate(db)
        try:
            MarketplaceRefreshService(db,fake).refresh(candidate.id)
            raise AssertionError("produto sem catálogo e sem item não deveria atualizar")
        except ValueError as exc:
            assert str(exc)=="PRODUCT_DETAILS_UNAVAILABLE"
        assert candidate.working_title is None
        assert not list(db.scalars(select(CuratorEvidence).where(CuratorEvidence.evidence_type.in_(["CURRENT_PRICE","LISTING_DATA","CATALOG_TITLE"]))))


def test_refresh_uses_official_capability_preserves_order_and_price_history():
    first = {"id":"MLB123456789","site_id":"MLB","title":"Parafusadeira doméstica","price":199.0,
        "original_price":249.0,"currency_id":"BRL","permalink":"https://produto.mercadolivre.com.br/MLB-123456789-item",
        "pictures":[{"id":"p1","secure_url":"https://img.example/p1.jpg","width":1200,"height":1200},{"id":"p2","url":"https://img.example/p2.jpg","width":800,"height":600}],
        "attributes":[{"id":"BRAND","name":"Marca","value_name":"Exemplo"}]}
    second = {**first, "price":179.0}
    fake = FakeClient([first, first, second])
    with SessionLocal() as db:
        candidate = CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL",entity_type="ITEM",external_id="MLB123456789")
        db.add_all([candidate, MarketplaceCapability(provider="MERCADO_LIVRE",capability_key="ITEM_DETAILS",status="AVAILABLE",
            metadata_={"itemId":"MLB123456789","itemProbes":{"MLB123456789":{"status":"AVAILABLE","httpStatus":200,"reasonCode":"HTTP_200"}}})]);db.commit()
        service = MarketplaceRefreshService(db, fake)
        result = service.refresh(candidate.id);service.refresh(candidate.id);service.refresh(candidate.id)
        assert result["title"] == "Parafusadeira doméstica"
        pictures = list(db.scalars(select(CuratorEvidence).where(CuratorEvidence.evidence_type == "LISTING_PICTURE").order_by(CuratorEvidence.source_reference)))
        assert [(x.value_json["position"],x.value_json["width"],x.value_json["height"]) for x in pictures] == [(0,1200,1200),(1,800,600)]
        assert db.scalar(select(func.count()).select_from(CuratorEvidence).where(CuratorEvidence.evidence_type == "CURRENT_PRICE")) == 2
        assert db.scalar(select(func.count()).select_from(CuratorEvidence).where(CuratorEvidence.evidence_type == "ATTRIBUTE")) == 1
        assert all(call[1].startswith("/items/") and call[2] == {"requires_auth": True} for call in fake.calls)


def test_refresh_rejects_restricted_item_details_without_remote_call():
    fake = FakeClient([])
    with SessionLocal() as db:
        candidate = CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL",entity_type="ITEM",external_id="MLB123456789")
        db.add_all([candidate, MarketplaceCapability(provider="MERCADO_LIVRE",capability_key="ITEM_DETAILS",status="FORBIDDEN",
            metadata_={"itemId":"MLB123456789","itemProbes":{"MLB123456789":{"status":"FORBIDDEN","httpStatus":403,
                "reasonCode":"HTTP_403","remoteErrorCode":"item_denied"}}})]);db.commit()
        try:
            MarketplaceRefreshService(db, fake).refresh(candidate.id)
            raise AssertionError("refresh deveria falhar")
        except ValueError as exc:
            assert str(exc) == "ITEM_DETAILS_UNAVAILABLE"
        assert fake.calls == []
        log=db.scalar(select(DecisionLog).where(DecisionLog.action=="MARKETPLACE_REFRESH_BLOCKED"))
        assert log.metadata_=={"stage":"CAPABILITY_CHECK","capability":"ITEM_DETAILS","capabilityStatus":"FORBIDDEN","provider":"MERCADO_LIVRE","siteId":"MLB","itemId":"MLB123456789","remoteErrorCode":"item_denied"}


def test_forbidden_item_probe_does_not_block_another_available_candidate():
    payload={"id":"MLB6000000001","title":"Item de controle","price":10.0,"pictures":[],"attributes":[]}
    fake=FakeClient([payload])
    with SessionLocal() as db:
        blocked=CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL",entity_type="ITEM",external_id="MLB6167651244")
        available=CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL",entity_type="ITEM",external_id="MLB6000000001")
        capability=MarketplaceCapability(provider="MERCADO_LIVRE",capability_key="ITEM_DETAILS",status="AVAILABLE",metadata_={
            "itemProbes":{"MLB6167651244":{"status":"FORBIDDEN","httpStatus":403,"reasonCode":"HTTP_403"},
                          "MLB6000000001":{"status":"AVAILABLE","httpStatus":200,"reasonCode":"HTTP_200"}}})
        db.add_all([blocked,available,capability]);db.commit()
        try:
            MarketplaceRefreshService(db,fake).refresh(blocked.id)
            raise AssertionError("item bloqueado não deveria atualizar")
        except ValueError as exc:
            assert str(exc)=="ITEM_DETAILS_UNAVAILABLE"
        result=MarketplaceRefreshService(db,fake).refresh(available.id)
        assert result["itemId"]=="MLB6000000001" and fake.calls==[("ITEM_DETAILS","/items/MLB6000000001",{"requires_auth":True})]
