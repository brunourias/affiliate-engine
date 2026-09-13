import json

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.app.core.config import settings
from apps.api.app.db.models import DecisionLog, MarketplaceCapability
from apps.api.app.db.session import SessionLocal
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.integrations.mercado_livre.diagnostics import MercadoLivreDiagnostics, parse_item_id


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
        assert db.scalar(select(func.count()).select_from(MarketplaceCapability)) == 13
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
