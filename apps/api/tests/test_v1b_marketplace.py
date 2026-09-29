import json

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate, DecisionLog, MarketplaceCapability, Notification
from apps.api.app.db.session import SessionLocal
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.integrations.mercado_livre.diagnostics import CAPABILITY_KEYS, MercadoLivreDiagnostics, parse_item_id
from apps.api.app.integrations.mercado_livre.models import CapabilityResult
from apps.api.app.services.mercado_livre_commercial import MarketplaceRefreshService

def test_discovery_source_failure_does_not_alert_while_group_remains_available():
    with SessionLocal() as db:
        for key in ["SITE","CATEGORIES","TRENDS_GLOBAL","TRENDS_CATEGORY","HIGHLIGHTS_CATEGORY"]: db.add(MarketplaceCapability(provider="MERCADO_LIVRE",capability_key=key,status="AVAILABLE"))
        db.commit(); service=MercadoLivreDiagnostics(db)
        service._persist(CapabilityResult("TRENDS_GLOBAL","DEGRADED","/trends/MLB"));db.commit()
        assert db.scalar(select(func.count(Notification.id))) == 0
        service.close()


def transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, json={"id": "MLB"}), "AVAILABLE"),
        (httpx.Response(401), "UNAUTHORIZED"),
        (httpx.Response(403), "FORBIDDEN"),
        (httpx.Response(404), "NOT_SUPPORTED"),
        (httpx.Response(429, headers={"Retry-After": "30"}), "DEGRADED"),
        (httpx.Response(503), "DEGRADED"),
    ],
)
def test_http_status_is_classified(response, expected):
    client = MercadoLivreClient(transport=transport(lambda request: response))
    try:
        assert client.get("SITE", "/sites/MLB").status == expected
    finally:
        client.close()


def test_timeout_is_degraded():
    def timeout(_request):
        raise httpx.ReadTimeout("timeout")
    client = MercadoLivreClient(transport=transport(timeout))
    try:
        result = client.get("SITE", "/sites/MLB")
        assert (result.status, result.reason_code) == ("DEGRADED", "TIMEOUT")
    finally:
        client.close()


def test_public_capability_does_not_send_configured_token_but_authenticated_one_does():
    headers=[]
    client=MercadoLivreClient("secret-token",transport=transport(lambda request:(headers.append((request.url.path,request.headers.get("Authorization"))),httpx.Response(200,json={"id":"ok"}))[1]))
    try:
        client.get("ITEM_DETAILS","/items/MLB1234567890")
        client.get("AUTH_USER","/users/me",requires_auth=True)
        assert headers == [("/items/MLB1234567890",None),("/users/me","Bearer secret-token")]
    finally:client.close()


def test_item_403_keeps_forbidden_and_extracts_only_allowlisted_error_fields():
    secret="token-must-never-leak"
    calls=[]
    def handler(request):
        calls.append((request.url.path,request.headers.get("Authorization")))
        return httpx.Response(403,json={
            "message":f"raw provider message {secret}","error":"forbidden","status":403,
            "code":"item_access_denied","cause":[{"code":"policy.denied","type":"policy","message":secret}],
            "unexpected":{"token":secret},
        })
    client=MercadoLivreClient(secret,transport=transport(handler))
    try:
        result=client.get("ITEM_DETAILS","/items/MLB6167651244")
        assert result.status=="FORBIDDEN" and result.reason_code=="HTTP_403"
        assert result.metadata=={"remoteStatus":403,"remoteErrorCode":"item_access_denied",
                                 "remoteErrorType":"forbidden","remoteCauseCode":"policy.denied",
                                 "remoteCauseType":"policy"}
        serialized=json.dumps(result.metadata)
        assert secret not in serialized and "raw provider message" not in serialized and "unexpected" not in serialized
        assert calls==[("/items/MLB6167651244",None)]
    finally:client.close()


def test_item_error_payload_rejects_unsafe_scalar_values_and_non_json_body():
    responses=iter([
        httpx.Response(403,json={"error":{"code":"token=abc 123","type":"forbidden"},"cause":{"code":"safe_code"}}),
        httpx.Response(403,text="raw body token=secret"),
    ])
    client=MercadoLivreClient(transport=transport(lambda request:next(responses)))
    try:
        first=client.get("ITEM_DETAILS","/items/MLB1111111111")
        second=client.get("ITEM_DETAILS","/items/MLB2222222222")
        assert first.metadata=={"remoteErrorType":"forbidden","remoteCauseCode":"safe_code"}
        assert second.metadata=={}
    finally:client.close()


def test_item_probes_are_scoped_and_one_forbidden_item_does_not_block_available_item():
    def handler(request):
        if request.url.path.endswith("MLB6167651244"):
            return httpx.Response(403,json={"error":"forbidden","status":403,"code":"item_denied"})
        return httpx.Response(200,json={"id":"MLB6000000001","title":"Item de controle"})
    provider=MercadoLivreClient("unused-token",transport=transport(handler))
    with SessionLocal() as db:
        service=MercadoLivreDiagnostics(db,provider)
        service.ensure_capabilities()
        service.fetch_item_details("MLB6167651244")
        service.fetch_item_details("MLB6000000001")
        blocked=service.item_details_probe("MLB6167651244")
        available=service.item_details_probe("MLB6000000001")
        aggregate=service.item_details_capability()
        assert blocked["status"]=="FORBIDDEN" and blocked["remoteErrorCode"]=="item_denied"
        assert available["status"]=="AVAILABLE"
        assert aggregate.status=="AVAILABLE"
        assert service.item_details_probe("MLB6999999999") is None
    provider.close()


def test_item_diagnostics_requires_authentication_and_sends_bearer_token():
    calls=[]
    provider=MercadoLivreClient("valid-token",transport=transport(lambda request:(
        calls.append((request.url.path,request.headers.get("Authorization"))),
        httpx.Response(200,json={"id":"MLB849301960"}),
    )[1]))
    with SessionLocal() as db:
        item_id,result=MercadoLivreDiagnostics(db,provider).fetch_item_details("MLB849301960")
        assert item_id=="MLB849301960" and result.status=="AVAILABLE"
        assert calls==[("/items/MLB849301960","Bearer valid-token")]
    provider.close()


def test_item_diagnostics_without_token_is_not_configured_and_makes_no_request():
    calls=[]
    provider=MercadoLivreClient("",transport=transport(lambda request:(calls.append(request),httpx.Response(200))[1]))
    with SessionLocal() as db:
        item_id,result=MercadoLivreDiagnostics(db,provider).fetch_item_details("MLB849301960")
        probe=MercadoLivreDiagnostics(db,provider).item_details_probe(item_id)
        assert (result.status,result.reason_code)==("NOT_CONFIGURED","TOKEN_NOT_CONFIGURED")
        assert probe["status"]=="NOT_CONFIGURED" and probe["reasonCode"]=="TOKEN_NOT_CONFIGURED"
        assert calls==[]
    provider.close()


def test_forbidden_provider_body_and_token_are_not_persisted_in_capability_or_decision_log():
    secret="never-persist-this-token"
    provider=MercadoLivreClient(secret,transport=transport(lambda request:httpx.Response(403,json={
        "status":403,"error":"forbidden","code":"item_denied","message":f"private {secret}",
        "cause":[{"code":"policy","type":"access","message":secret}],
    })))
    with SessionLocal() as db:
        MercadoLivreDiagnostics(db,provider).run_item("MLB6167651244")
        persisted=json.dumps({
            "capabilities":[row.metadata_ for row in db.scalars(select(MarketplaceCapability))],
            "decisions":[row.metadata_ for row in db.scalars(select(DecisionLog))],
        })
        assert secret not in persisted and "private" not in persisted
        assert "item_denied" in persisted and "policy" in persisted
    provider.close()


def test_item_diagnostics_and_refresh_share_persisted_capability_and_official_client(monkeypatch):
    monkeypatch.setattr(settings,"meli_access_token","configured-token")
    calls=[]
    def handler(request):
        calls.append((request.url.path,request.headers.get("Authorization")))
        if request.url.path=="/items/MLB6167651244":
            return httpx.Response(200,json={"id":"MLB6167651244","title":"Câmera inteligente","price":299.9,"currency_id":"BRL","pictures":[],"attributes":[]})
        return httpx.Response(200,json={})
    provider=MercadoLivreClient("configured-token",transport=transport(handler))
    with SessionLocal() as db:
        candidate=CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL",entity_type="ITEM",external_id="MLB6167651244")
        db.add(candidate);db.commit()
        diagnostics=MercadoLivreDiagnostics(db,provider);diagnostics.run_item("MLB6167651244")
        capability=diagnostics.item_details_capability()
        assert capability.status=="AVAILABLE" and capability.metadata_["itemId"]=="MLB6167651244"
        result=MarketplaceRefreshService(db,provider).refresh(candidate.id)
        assert result["itemId"]=="MLB6167651244" and result["title"]=="Câmera inteligente"
        item_calls=[item for item in calls if item[0]=="/items/MLB6167651244"]
        assert item_calls==[("/items/MLB6167651244","Bearer configured-token"),("/items/MLB6167651244","Bearer configured-token")]
    provider.close()


def test_item_id_parser_never_invents_identifier():
    assert parse_item_id("MLB-1234567890") == "MLB1234567890"
    assert parse_item_id("https://produto.mercadolivre.com.br/MLB-1234567890-nome-_JM") == "MLB1234567890"
    assert parse_item_id("https://example.com/MLB-1234567890") is None
    assert parse_item_id("https://evilmercadolivre.com/MLB-1234567890") is None
    assert parse_item_id("https://produto.mercadolivre.com.br/anuncio-sem-id") is None


def test_general_diagnostic_persists_updates_and_search_is_optional(monkeypatch):
    monkeypatch.setattr(settings, "meli_access_token", "")
    calls = {"trends": 0, "search_forbidden": True}
    def handler(request):
        if request.url.path.endswith("/search") and calls["search_forbidden"]:
            return httpx.Response(403)
        if request.url.path.startswith("/trends/"):
            calls["trends"] += 1
        return httpx.Response(200, json={"id": "ok"})
    client = MercadoLivreClient(transport=transport(handler))
    with SessionLocal() as db:
        service = MercadoLivreDiagnostics(db, client)
        first = service.run("MLB5672")
        assert first.status == "AVAILABLE"
        assert first.auth_mode == "ANONYMOUS"
        assert db.scalar(select(MarketplaceCapability.status).where(MarketplaceCapability.capability_key == "MARKETPLACE_SEARCH")) == "FORBIDDEN"
        assert db.scalar(select(MarketplaceCapability.status).where(MarketplaceCapability.capability_key == "AUTH_USER")) == "NOT_CONFIGURED"
        calls["search_forbidden"] = False
        service.run("MLB5672")
        assert db.scalar(select(func.count()).select_from(MarketplaceCapability)) == len(CAPABILITY_KEYS)
        assert db.scalar(select(MarketplaceCapability.status).where(MarketplaceCapability.capability_key == "MARKETPLACE_SEARCH")) == "AVAILABLE"
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "MARKETPLACE_CAPABILITY_CHANGED")) >= 1
        assert db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.action == "MARKETPLACE_DIAGNOSTICS_RUN")) == 2
    client.close()


def test_item_dependencies_and_secret_are_not_persisted(monkeypatch):
    secret = "token-super-secreto"
    monkeypatch.setattr(settings, "meli_access_token", secret)
    def handler(request):
        if request.url.path == "/items/MLB1234567890":
            return httpx.Response(200, json={"id": "MLB1234567890", "seller_id": 42, "catalog_product_id": None, "user_product_id": None})
        return httpx.Response(200, json={"ok": True})
    client = MercadoLivreClient(secret, transport=transport(handler))
    with SessionLocal() as db:
        service = MercadoLivreDiagnostics(db, client)
        connection = service.run_item("MLB1234567890")
        statuses = {row.capability_key: row.status for row in db.scalars(select(MarketplaceCapability))}
        assert statuses["CATALOG_PRODUCT"] == "NOT_APPLICABLE"
        assert statuses["USER_PRODUCT"] == "NOT_APPLICABLE"
        serialized = json.dumps({"connection": connection.metadata_, "capabilities": [row.metadata_ for row in db.scalars(select(MarketplaceCapability))]})
        assert secret not in serialized
    client.close()


def test_marketplace_read_endpoints_expose_no_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "meli_access_token", "token-nao-pode-sair")
    connection = client.get("/api/v1/marketplaces/mercado-livre")
    capabilities = client.get("/api/v1/marketplaces/mercado-livre/capabilities")
    assert connection.status_code == capabilities.status_code == 200
    assert "token-nao-pode-sair" not in connection.text + capabilities.text


def test_connection_available_when_search_and_item_are_forbidden(monkeypatch):
    monkeypatch.setattr(settings, "meli_access_token", "configured")
    def handler(request):
        if request.url.path.endswith("/search"):
            return httpx.Response(403)
        return httpx.Response(200, json={"id": "ok"})
    provider = MercadoLivreClient("configured", transport=transport(handler))
    with SessionLocal() as db:
        db.add(MarketplaceCapability(provider="MERCADO_LIVRE", capability_key="ITEM_DETAILS", status="FORBIDDEN")); db.commit()
        connection = MercadoLivreDiagnostics(db, provider).run("MLB5672")
        assert connection.status == "AVAILABLE"
        assert db.scalar(select(MarketplaceCapability.status).where(MarketplaceCapability.capability_key == "ITEM_DETAILS")) == "FORBIDDEN"
    provider.close()
