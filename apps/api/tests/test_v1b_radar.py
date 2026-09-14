import json

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.app.db.models import AppSettings, MarketplaceCapability, MarketplaceCategory, RadarRun, RadarSignal
from apps.api.app.db.session import SessionLocal
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.integrations.mercado_livre.radar import MercadoLivreRadar, RadarDomainError


def seed_capabilities(db, *, categories="AVAILABLE", global_trends="AVAILABLE", category_trends="AVAILABLE", highlights="AVAILABLE"):
    values = {"SITE": "AVAILABLE", "CATEGORIES": categories, "TRENDS_GLOBAL": global_trends, "TRENDS_CATEGORY": category_trends, "HIGHLIGHTS_CATEGORY": highlights, "MARKETPLACE_SEARCH": "FORBIDDEN", "ITEM_DETAILS": "FORBIDDEN"}
    for key, status in values.items(): db.add(MarketplaceCapability(provider="MERCADO_LIVRE", capability_key=key, status=status))
    db.commit()


def mock_client(handler, token="test-token"):
    return MercadoLivreClient(token, transport=httpx.MockTransport(handler))


def enable_radar(db, automation=True):
    row = db.get(AppSettings, 1); row.radar_enabled = True; row.system_automation_enabled = automation; db.commit()


def add_category(db):
    row = MarketplaceCategory(provider="MERCADO_LIVRE", site_id="MLB", external_category_id="MLB5672", name="Acessórios", source_capability="CATEGORIES")
    db.add(row); db.commit(); return row


def discovery_handler(fail=()):
    def handler(request):
        path = request.url.path
        if any(key in path for key in fail): return httpx.Response(429)
        if path == "/trends/MLB": return httpx.Response(200, json=[{"keyword": "parafusadeira"}, {"keyword": "furadeira", "position": 7}])
        if path == "/trends/MLB/MLB5672": return httpx.Response(200, json=[{"keyword": "chave de impacto"}])
        if path == "/highlights/MLB/category/MLB5672": return httpx.Response(200, json={"content": [{"id": "MLB1", "type": "ITEM", "position": 2}, {"id": "MLB2", "type": "PRODUCT", "position": 3}, {"id": "MLBU3", "type": "USER_PRODUCT", "position": 4}, {"id": "OTHER4", "type": "OTHER", "position": 5}]})
        raise AssertionError(f"Endpoint proibido chamado pelo Radar: {path}")
    return handler


def test_connection_is_available_with_search_and_item_forbidden():
    with SessionLocal() as db:
        seed_capabilities(db)
        assert MercadoLivreRadar(db, mock_client(discovery_handler())).status()["status"] == "AVAILABLE"


def test_radar_is_unavailable_without_categories():
    with SessionLocal() as db:
        seed_capabilities(db, categories="FORBIDDEN")
        assert MercadoLivreRadar(db, mock_client(discovery_handler())).status()["status"] == "UNAVAILABLE"


def test_category_sync_insert_update_and_idempotence():
    payload = [{"id": "MLB5672", "name": "Ferramentas"}]
    client = mock_client(lambda request: httpx.Response(200, json=payload))
    with SessionLocal() as db:
        seed_capabilities(db)
        service = MercadoLivreRadar(db, client)
        assert service.sync_categories() == {"fetched": 1, "inserted": 1, "updated": 0}
        first_seen = db.scalar(select(MarketplaceCategory.first_seen_at))
        assert service.sync_categories() == {"fetched": 1, "inserted": 0, "updated": 0}
        payload[0]["name"] = "Ferramentas e construção"
        assert service.sync_categories() == {"fetched": 1, "inserted": 0, "updated": 1}
        assert db.scalar(select(func.count()).select_from(MarketplaceCategory)) == 1
        assert db.scalar(select(MarketplaceCategory.first_seen_at)) == first_seen
    client.close()


def test_completed_run_normalizes_trends_and_preserves_highlight_types():
    called = []
    base_handler = discovery_handler()
    def handler(request): called.append(request.url.path); return base_handler(request)
    client = mock_client(handler)
    with SessionLocal() as db:
        seed_capabilities(db); enable_radar(db); add_category(db)
        run = MercadoLivreRadar(db, client).run("MLB5672")
        signals = db.scalars(select(RadarSignal).where(RadarSignal.radar_run_id == run.id)).all()
        assert run.status == "COMPLETED" and run.discovered_count == 7
        assert {(s.display_text, s.rank) for s in signals if s.source_type == "TREND_GLOBAL"} == {("parafusadeira", 1), ("furadeira", 7)}
        assert all(s.category_external_id == "MLB5672" for s in signals if s.source_type == "TREND_CATEGORY")
        assert {(s.external_id, s.entity_type, s.rank) for s in signals if s.source_type == "HIGHLIGHT_CATEGORY"} == {("MLB1", "ITEM", 2), ("MLB2", "PRODUCT", 3), ("MLBU3", "USER_PRODUCT", 4), ("OTHER4", "UNKNOWN", 5)}
        assert not any("search" in path or "/items/" in path for path in called)
    client.close()


def test_partial_run_keeps_successful_signals():
    client = mock_client(discovery_handler(fail=("highlights",)))
    with SessionLocal() as db:
        seed_capabilities(db); enable_radar(db); add_category(db)
        run = MercadoLivreRadar(db, client).run("MLB5672")
        assert run.status == "PARTIAL" and run.sources_failed == ["HIGHLIGHTS_CATEGORY"]
        assert run.discovered_count == 3
    client.close()


def test_failed_run_when_all_requested_sources_fail():
    client = mock_client(discovery_handler(fail=("trends", "highlights")))
    with SessionLocal() as db:
        seed_capabilities(db); enable_radar(db); add_category(db)
        run = MercadoLivreRadar(db, client).run("MLB5672")
        assert run.status == "FAILED" and run.discovered_count == 0
    client.close()


def test_radar_disabled_blocks_execution():
    with SessionLocal() as db:
        seed_capabilities(db)
        with pytest.raises(RadarDomainError, match="desativado"):
            MercadoLivreRadar(db, mock_client(discovery_handler())).run()


def test_global_kill_switch_does_not_block_manual_run():
    client = mock_client(discovery_handler())
    with SessionLocal() as db:
        seed_capabilities(db); enable_radar(db, automation=False)
        run = MercadoLivreRadar(db, client).run()
        assert run.trigger_type == "MANUAL" and run.status == "COMPLETED"
    client.close()


def test_invalid_or_unsynced_category_is_rejected():
    with SessionLocal() as db:
        seed_capabilities(db); enable_radar(db)
        service = MercadoLivreRadar(db, mock_client(discovery_handler()))
        with pytest.raises(RadarDomainError, match="inválida"): service.run("INVALID")
        with pytest.raises(RadarDomainError, match="não encontrada"): service.run("MLB5672")


def test_persisted_payload_excludes_credentials():
    secret = "token-super-secreto"
    def handler(request):
        return httpx.Response(200, json=[{"keyword": "serra", "authorization": secret, "cookie": secret}])
    client = mock_client(handler, secret)
    with SessionLocal() as db:
        seed_capabilities(db, category_trends="FORBIDDEN", highlights="FORBIDDEN"); enable_radar(db)
        run = MercadoLivreRadar(db, client).run()
        payload = db.scalar(select(RadarSignal.source_payload).where(RadarSignal.radar_run_id == run.id))
        assert secret not in json.dumps(payload)
    client.close()


def test_radar_api_history_and_signals(client, monkeypatch):
    with SessionLocal() as db:
        seed_capabilities(db); enable_radar(db)
    monkeypatch.setattr("apps.api.app.api.routes.MercadoLivreRadar", lambda db: MercadoLivreRadar(db, mock_client(discovery_handler())))
    created = client.post("/api/v1/radar/mercado-livre/runs", json={})
    assert created.status_code == 201
    run_id = created.json()["id"]
    assert client.get("/api/v1/radar/mercado-livre/runs").json()[0]["id"] == run_id
    assert client.get(f"/api/v1/radar/mercado-livre/runs/{run_id}").status_code == 200
    assert client.get(f"/api/v1/radar/mercado-livre/runs/{run_id}/signals").json()[0]["entityType"] == "QUERY"
    assert client.post("/api/v1/radar/mercado-livre/runs", json={"categoryId": "bad"}).status_code == 422
