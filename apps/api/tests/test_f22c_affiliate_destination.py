import httpx
from sqlalchemy import func, select

from apps.api.app.db.models import CuratorCandidate, CuratorEvidence
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.mercado_livre_commercial import AffiliateDestinationService, AffiliateLinkResolver


PUBLIC_DNS = lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))]


def resolver(handler, *, dns=PUBLIC_DNS, max_redirects=5):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return AffiliateLinkResolver(client, dns_resolver=dns, max_redirects=max_redirects)


def candidate(db):
    row = CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL",entity_type="ITEM",
        external_id="MLB123456789",source_url="https://produto.mercadolivre.com.br/MLB-123456789-produto")
    db.add(row);db.commit();return row


def test_short_link_resolves_safely_to_same_item_and_is_idempotent():
    def handler(request):
        if request.url.host == "meli.la":
            return httpx.Response(302, headers={"Location":"https://produto.mercadolivre.com.br/MLB-123456789-produto?tracking=official"})
        return httpx.Response(200)
    with SessionLocal() as db:
        row=candidate(db);service=AffiliateDestinationService(db,resolver(handler))
        result=service.configure(row.id,"https://meli.la/abc","DIRECT_AFFILIATE_LINK")
        service.configure(row.id,"https://meli.la/abc","DIRECT_AFFILIATE_LINK")
        assert result["affiliateValidationStatus"] == "VALID"
        assert result["affiliateItemId"] == "MLB123456789"
        assert result["destinationUrl"] == "https://meli.la/abc"
        assert db.scalar(select(func.count()).select_from(CuratorEvidence).where(CuratorEvidence.evidence_type=="AFFILIATE_DESTINATION")) == 1


def test_redirect_to_other_item_is_invalid():
    def handler(request):
        return httpx.Response(302,headers={"Location":"https://produto.mercadolivre.com.br/MLB-987654321-outro"}) if request.url.host=="meli.la" else httpx.Response(200)
    with SessionLocal() as db:
        row=candidate(db);result=AffiliateDestinationService(db,resolver(handler)).configure(row.id,"https://meli.la/outro","DIRECT_AFFILIATE_LINK")
        assert (result["affiliateValidationStatus"],result["failureCode"]) == ("INVALID","AFFILIATE_ITEM_MISMATCH")
        assert result["destinationUrl"] is None


def test_unresolved_item_is_unverified_and_not_ready():
    with SessionLocal() as db:
        row=candidate(db);result=AffiliateDestinationService(db,resolver(lambda request:httpx.Response(200))).configure(row.id,"https://meli.la/sem-item","DIRECT_AFFILIATE_LINK")
        assert result["affiliateValidationStatus"] == "UNVERIFIED"
        assert result["destinationUrl"] is None


def test_home_search_category_and_source_permalink_are_invalid():
    with SessionLocal() as db:
        row=candidate(db)
        for url in ("https://www.mercadolivre.com.br/", "https://lista.mercadolivre.com.br/search/produto", "https://www.mercadolivre.com.br/categorias/ferramentas", row.source_url):
            result=AffiliateDestinationService(db,resolver(lambda request:httpx.Response(200))).configure(row.id,url,"DIRECT_AFFILIATE_LINK")
            assert result["affiliateValidationStatus"] == "INVALID"


def test_redirect_limit_and_non_allowed_redirect_are_blocked():
    endless=resolver(lambda request:httpx.Response(302,headers={"Location":"https://meli.la/again"}),max_redirects=1)
    assert endless.resolve("https://meli.la/start")["failureCode"] == "AFFILIATE_REDIRECT_LIMIT"
    external=resolver(lambda request:httpx.Response(302,headers={"Location":"https://example.com/MLB123456789"}))
    assert external.resolve("https://meli.la/start")["failureCode"] == "AFFILIATE_HOST_NOT_ALLOWED"


def test_localhost_private_ip_and_unsafe_schemes_are_blocked_without_request():
    calls=[]
    r=resolver(lambda request:(calls.append(request),httpx.Response(200))[1],dns=lambda *args,**kwargs:[(2,1,6,"",("127.0.0.1",443))])
    assert r.resolve("https://meli.la/test")["failureCode"] == "AFFILIATE_PRIVATE_ADDRESS_BLOCKED"
    assert r.resolve("http://meli.la/test")["status"] == "INVALID"
    assert r.resolve("file:///tmp/test")["status"] == "INVALID"
    assert r.resolve("https://localhost/test")["status"] == "INVALID"
    assert calls == []


def test_timeout_is_unverified_and_does_not_expose_request_data():
    def timeout(request): raise httpx.ReadTimeout("timeout",request=request)
    result=resolver(timeout).resolve("https://meli.la/private-tracking-value")
    assert result["status"] == "UNVERIFIED"
    assert "private-tracking-value" not in str(result)
