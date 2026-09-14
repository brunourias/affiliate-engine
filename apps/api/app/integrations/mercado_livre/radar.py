import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import AppSettings, MarketplaceCapability, MarketplaceCategory, RadarRun, RadarSignal
from apps.api.app.services.operations import log_decision, notify
from .client import MercadoLivreClient
from .diagnostics import PROVIDER

CATEGORY_PATTERN = re.compile(r"^MLB\d+$")
DISCOVERY = ("TRENDS_GLOBAL", "TRENDS_CATEGORY", "HIGHLIGHTS_CATEGORY")
SOURCE_TYPES = {"TRENDS_GLOBAL": "TREND_GLOBAL", "TRENDS_CATEGORY": "TREND_CATEGORY", "HIGHLIGHTS_CATEGORY": "HIGHLIGHT_CATEGORY"}


class RadarDomainError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def radar_status(capabilities: dict[str, str]) -> str:
    basics = capabilities.get("SITE") == "AVAILABLE" and capabilities.get("CATEGORIES") == "AVAILABLE"
    discovery = any(capabilities.get(key) == "AVAILABLE" for key in DISCOVERY)
    if basics and discovery:
        return "AVAILABLE"
    if basics:
        return "DEGRADED"
    return "UNAVAILABLE"


class MercadoLivreRadar:
    def __init__(self, db: Session, client: MercadoLivreClient | None = None):
        self.db = db
        self.client = client or MercadoLivreClient(settings.meli_access_token)
        self._owns_client = client is None
        self.site = settings.meli_site_id or "MLB"

    def close(self):
        if self._owns_client:
            self.client.close()

    def capabilities(self) -> dict[str, str]:
        return {row.capability_key: row.status for row in self.db.scalars(select(MarketplaceCapability).where(MarketplaceCapability.provider == PROVIDER))}

    def status(self) -> dict[str, Any]:
        capabilities = self.capabilities()
        return {"provider": PROVIDER, "siteId": self.site, "status": radar_status(capabilities), "capabilities": capabilities}

    def sync_categories(self) -> dict[str, int]:
        if self.capabilities().get("CATEGORIES") != "AVAILABLE":
            raise RadarDomainError("A capacidade oficial de categorias não está disponível.")
        result = self.client.get("CATEGORIES", f"/sites/{self.site}/categories")
        if result.status != "AVAILABLE" or not isinstance(result.data, list):
            raise RadarDomainError(result.message or "Não foi possível consultar as categorias oficiais.")
        now = utcnow(); inserted = updated = 0
        for item in result.data:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("name"), str):
                continue
            external_id = item["id"]
            row = self.db.scalar(select(MarketplaceCategory).where(MarketplaceCategory.provider == PROVIDER, MarketplaceCategory.external_category_id == external_id))
            if row is None:
                row = MarketplaceCategory(provider=PROVIDER, site_id=self.site, external_category_id=external_id, name=item["name"], parent_external_category_id=item.get("parent_id"), source_capability="CATEGORIES", first_seen_at=now, last_seen_at=now)
                self.db.add(row); inserted += 1
            else:
                changed = row.name != item["name"] or row.parent_external_category_id != item.get("parent_id")
                row.name = item["name"]; row.parent_external_category_id = item.get("parent_id"); row.last_seen_at = now; row.updated_at = now
                updated += int(changed)
        fetched = len(result.data)
        log_decision(self.db, "OPERATOR", "MARKETPLACE_CATEGORY", "RADAR_CATEGORIES_SYNCED", reason="Categorias oficiais sincronizadas", metadata={"provider": PROVIDER, "fetched": fetched, "inserted": inserted, "updated": updated})
        self.db.commit()
        return {"fetched": fetched, "inserted": inserted, "updated": updated}

    def run(self, category_id: str | None = None) -> RadarRun:
        app_settings = self.db.get(AppSettings, 1)
        if app_settings is None or not app_settings.radar_enabled:
            raise RadarDomainError("O Radar está desativado nas Configurações.")
        if category_id:
            if not CATEGORY_PATTERN.fullmatch(category_id):
                raise RadarDomainError("Categoria inválida. Selecione uma categoria MLB sincronizada.")
            exists = self.db.scalar(select(MarketplaceCategory.id).where(MarketplaceCategory.provider == PROVIDER, MarketplaceCategory.external_category_id == category_id))
            if not exists:
                raise RadarDomainError("Categoria não encontrada. Sincronize as categorias antes de executar.")
        capabilities = self.capabilities()
        if radar_status(capabilities) == "UNAVAILABLE":
            raise RadarDomainError("O conjunto mínimo de capacidades do Radar não está disponível.")
        sources = []
        if capabilities.get("TRENDS_GLOBAL") == "AVAILABLE": sources.append("TRENDS_GLOBAL")
        if category_id and capabilities.get("TRENDS_CATEGORY") == "AVAILABLE": sources.append("TRENDS_CATEGORY")
        if category_id and capabilities.get("HIGHLIGHTS_CATEGORY") == "AVAILABLE": sources.append("HIGHLIGHTS_CATEGORY")
        if not sources:
            raise RadarDomainError("Nenhuma fonte disponível pode ser executada com os parâmetros informados.")
        run = RadarRun(provider=PROVIDER, site_id=self.site, trigger_type="MANUAL", status="RUNNING", requested_category_id=category_id, sources_requested=sources, sources_succeeded=[], sources_failed=[])
        self.db.add(run); self.db.flush()
        log_decision(self.db, "OPERATOR", "RADAR_RUN", "RADAR_RUN_STARTED", run.id, metadata={"provider": PROVIDER, "categoryId": category_id, "sources": sources, "runId": run.id})
        self.db.commit(); self.db.refresh(run)
        succeeded: list[str] = []; failed: list[str] = []
        for source in sources:
            endpoint = self._endpoint(source, category_id)
            result = self.client.get(source, endpoint, requires_auth=source == "HIGHLIGHTS_CATEGORY")
            if result.status == "AVAILABLE":
                self._persist_signals(run, source, category_id, result.data)
                succeeded.append(source)
            else:
                failed.append(source)
        run.sources_succeeded = succeeded; run.sources_failed = failed
        run.discovered_count = len(self.db.scalars(select(RadarSignal).where(RadarSignal.radar_run_id == run.id)).all())
        run.status = "COMPLETED" if not failed else "FAILED" if not succeeded else "PARTIAL"
        run.error_summary = None if not failed else f"Falha em {len(failed)} de {len(sources)} fonte(s)."
        run.finished_at = utcnow(); run.updated_at = run.finished_at
        action = f"RADAR_RUN_{run.status}"
        log_decision(self.db, "SYSTEM", "RADAR_RUN", action, run.id, metadata={"provider": PROVIDER, "categoryId": category_id, "sourcesSucceeded": succeeded, "sourcesFailed": failed, "count": run.discovered_count, "runId": run.id})
        previous_status = self.db.scalar(select(RadarRun.status).where(RadarRun.provider == PROVIDER, RadarRun.id != run.id).order_by(RadarRun.started_at.desc()).limit(1))
        if run.status == "FAILED" and previous_status != "FAILED":
            notify(self.db, "WARNING", "Radar sem fontes disponíveis", "Todas as fontes solicitadas falharam nesta execução.", "RADAR", {"runId": run.id})
        self.db.commit(); self.db.refresh(run)
        return run

    def _endpoint(self, source: str, category_id: str | None) -> str:
        if source == "TRENDS_GLOBAL": return f"/trends/{self.site}"
        if source == "TRENDS_CATEGORY": return f"/trends/{self.site}/{category_id}"
        return f"/highlights/{self.site}/category/{category_id}"

    def _persist_signals(self, run: RadarRun, source: str, category_id: str | None, data: Any):
        items = data.get("content", []) if source == "HIGHLIGHTS_CATEGORY" and isinstance(data, dict) else data
        if not isinstance(items, list):
            return
        seen: set[tuple] = set(); observed = utcnow()
        for index, item in enumerate(items, 1):
            if not isinstance(item, dict): continue
            if source == "HIGHLIGHTS_CATEGORY":
                raw_type = str(item.get("type", "UNKNOWN")).upper()
                entity_type = raw_type if raw_type in {"ITEM", "PRODUCT", "USER_PRODUCT"} else "UNKNOWN"
                external_id = str(item["id"]) if item.get("id") is not None else None
                display_text = None
                payload = {key: item[key] for key in ("id", "type", "position") if key in item}
            else:
                entity_type = "QUERY"; external_id = None
                value = item.get("keyword") or item.get("query") or item.get("name")
                display_text = str(value) if value is not None else None
                payload = {key: item[key] for key in ("keyword", "query", "name", "url", "position") if key in item}
            position = item.get("position")
            rank = position if isinstance(position, int) else index
            identity = (source, category_id, entity_type, external_id, display_text, rank)
            if identity in seen: continue
            seen.add(identity)
            self.db.add(RadarSignal(radar_run_id=run.id, provider=PROVIDER, site_id=self.site, source_type=SOURCE_TYPES[source], source_capability=source, category_external_id=category_id if source != "TRENDS_GLOBAL" else None, entity_type=entity_type, external_id=external_id, display_text=display_text, rank=rank, source_payload=payload, observed_at=observed))
        self.db.flush()
