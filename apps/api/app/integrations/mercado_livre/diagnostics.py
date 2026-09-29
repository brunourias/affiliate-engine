import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, unquote, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import MarketplaceCapability, MarketplaceConnection
from apps.api.app.services.operations import log_decision, notify
from .client import MercadoLivreClient
from .models import CapabilityResult
from .oauth import MercadoLivreTokenManager

PROVIDER = "MERCADO_LIVRE"
CAPABILITY_KEYS = ["SITE", "CATEGORIES", "TRENDS_GLOBAL", "TRENDS_CATEGORY", "HIGHLIGHTS_CATEGORY", "MARKETPLACE_SEARCH", "AUTH_USER", "ITEM_DETAILS", "ITEM_DESCRIPTION", "PRICE_DETAILS", "REVIEWS", "SELLER_DETAILS", "CATALOG_PRODUCT", "USER_PRODUCT"]
FOUNDATIONS = {"SITE", "CATEGORIES"}
DISCOVERY = {"TRENDS_GLOBAL", "TRENDS_CATEGORY", "HIGHLIGHTS_CATEGORY"}
ITEM_PATTERN = re.compile(r"(?<![A-Z0-9])(MLB-?\d{6,})(?!\d)", re.IGNORECASE)
ITEM_EXACT_PATTERN = re.compile(r"^MLB-?\d{6,}$", re.IGNORECASE)
CATALOG_PATH_PATTERN = re.compile(r"/p/(MLB-?\d{6,})(?:[/_-]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class MercadoLivreItemReference:
    source_item_id: str | None
    catalog_product_id: str | None = None
    resolution_method: str | None = None

    @property
    def item_id(self) -> str | None:
        """Compatibility alias: item means the observed commercial offer, never the catalog PDP."""
        return self.source_item_id


def _normalized_item(value: str) -> str | None:
    return value.upper().replace("-", "") if ITEM_EXACT_PATTERN.fullmatch(value.strip()) else None


def parse_item_reference(value: str) -> MercadoLivreItemReference:
    text = unquote(value.strip())
    if "://" not in text:
        item_id = _normalized_item(text)
        return MercadoLivreItemReference(item_id, None, "EXPLICIT_ITEM_ID" if item_id else None)
    parsed = urlparse(text)
    hostname = parsed.hostname or ""
    allowed_host = any(hostname == domain or hostname.endswith(f".{domain}") for domain in ("mercadolivre.com.br", "mercadolibre.com"))
    if parsed.scheme not in {"http", "https"} or not allowed_host:
        return MercadoLivreItemReference(None)
    catalog_match = CATALOG_PATH_PATTERN.search(parsed.path)
    catalog_id = _normalized_item(catalog_match.group(1)) if catalog_match else None
    parameters = [*parse_qsl(parsed.query, keep_blank_values=True), *parse_qsl(parsed.fragment, keep_blank_values=True)]
    wid_values = [value for key, value in parameters if key.lower() == "wid"]
    commercial_id = next((item for item in (_normalized_item(value) for value in wid_values) if item), None)
    if commercial_id:
        return MercadoLivreItemReference(commercial_id, catalog_id, "WID_COMMERCIAL_OFFER")
    match = ITEM_PATTERN.search(parsed.path)
    fallback = _normalized_item(match.group(1)) if match and not catalog_id else None
    return MercadoLivreItemReference(fallback, catalog_id,
                                     "CATALOG_PRODUCT_PATH" if catalog_id else "DIRECT_ITEM_PATH" if fallback else None)


def utcnow():
    return datetime.now(timezone.utc)


def parse_item_id(value: str) -> str | None:
    return parse_item_reference(value).item_id


class MercadoLivreDiagnostics:
    def __init__(self, db: Session, client: MercadoLivreClient | None = None):
        self.db = db
        self.client = client or MercadoLivreClient(token_manager=MercadoLivreTokenManager(db))
        self._owns_client = client is None
        self.site = settings.meli_site_id or "MLB"

    def close(self):
        if self._owns_client:
            self.client.close()

    def connection(self) -> MarketplaceConnection:
        row = self.db.scalar(select(MarketplaceConnection).where(MarketplaceConnection.provider == PROVIDER))
        if row is None:
            row = MarketplaceConnection(provider=PROVIDER, site_id=self.site, auth_mode=self.auth_mode, metadata_={"baseUrl": "https://api.mercadolibre.com"})
            self.db.add(row); self.db.flush()
        row.site_id = self.site
        row.auth_mode = self.auth_mode
        return row

    @property
    def auth_mode(self) -> str:
        return self.client.token_manager.auth_mode if self.client.token_manager else "ENV_ACCESS_TOKEN" if self.client.access_token else "ANONYMOUS"

    def ensure_capabilities(self):
        existing = {row.capability_key for row in self.db.scalars(select(MarketplaceCapability).where(MarketplaceCapability.provider == PROVIDER))}
        for key in CAPABILITY_KEYS:
            if key not in existing:
                self.db.add(MarketplaceCapability(provider=PROVIDER, capability_key=key, status="UNKNOWN"))
        self.db.commit()

    def run(self, category_id: str | None = None) -> MarketplaceConnection:
        self.ensure_capabilities()
        category = category_id or f"{self.site}5672"
        checks = [
            self.client.get("SITE", f"/sites/{self.site}"),
            self.client.get("CATEGORIES", f"/sites/{self.site}/categories"),
            self.client.get("TRENDS_GLOBAL", f"/trends/{self.site}"),
            self.client.get("TRENDS_CATEGORY", f"/trends/{self.site}/{category}"),
            self.client.get("HIGHLIGHTS_CATEGORY", f"/highlights/{self.site}/category/{category}", requires_auth=True),
            self.client.get("MARKETPLACE_SEARCH", f"/sites/{self.site}/search", params={"q": "ferramentas"}),
            self.client.get("AUTH_USER", "/users/me", requires_auth=True),
        ]
        for result in checks:
            self._persist(result)
        auth = next(item for item in checks if item.key == "AUTH_USER")
        connection = self.connection()
        if auth.status == "AVAILABLE" and isinstance(auth.data, dict):
            connection.external_account_id = str(auth.data.get("id")) if auth.data.get("id") is not None else None
            connection.external_nickname = auth.data.get("nickname")
        self._finish_connection(connection)
        log_decision(self.db, "OPERATOR", "MARKETPLACE_CONNECTION", "MARKETPLACE_DIAGNOSTICS_RUN", connection.id, metadata={"provider": PROVIDER, "categoryId": category})
        self.db.commit(); self.db.refresh(connection)
        return connection

    def run_item(self, value: str) -> MarketplaceConnection:
        self.ensure_capabilities()
        item_id, item = self.fetch_item_details(value)
        if item.status != "AVAILABLE" or not isinstance(item.data, dict):
            for key in ["ITEM_DESCRIPTION", "PRICE_DETAILS", "REVIEWS", "SELLER_DETAILS", "USER_PRODUCT"]:
                self._persist(CapabilityResult(key, "NOT_APPLICABLE", None, reason_code="ITEM_UNAVAILABLE", message="Depende de detalhes válidos do item."))
        else:
            data = item.data
            self._persist(self.client.get("ITEM_DESCRIPTION", f"/items/{item_id}/description", requires_auth=True), {"itemId": item_id})
            self._persist(self.client.get("PRICE_DETAILS", f"/items/{item_id}/sale_price", requires_auth=True), {"itemId": item_id})
            self._persist(self.client.get("REVIEWS", f"/reviews/item/{item_id}", requires_auth=True), {"itemId": item_id})
            seller_id = data.get("seller_id")
            self._persist(self.client.get("SELLER_DETAILS", f"/users/{seller_id}", requires_auth=True) if seller_id else CapabilityResult("SELLER_DETAILS", "NOT_APPLICABLE", None, reason_code="SELLER_ID_ABSENT", message="O item não informou seller_id."))
            catalog_id = data.get("catalog_product_id")
            if catalog_id:
                self.fetch_catalog_product(str(catalog_id))
            else:
                self._persist(CapabilityResult("CATALOG_PRODUCT", "NOT_APPLICABLE", None,
                    reason_code="CATALOG_PRODUCT_ID_ABSENT", message="O item não está associado a produto de catálogo."))
            user_product_id = data.get("user_product_id")
            self._persist(self.client.get("USER_PRODUCT", f"/user-products/{user_product_id}", requires_auth=True) if user_product_id else CapabilityResult("USER_PRODUCT", "NOT_APPLICABLE", None, reason_code="USER_PRODUCT_ID_ABSENT", message="O item não informou user_product_id."))
        connection = self.connection(); self._finish_connection(connection)
        log_decision(self.db, "OPERATOR", "MARKETPLACE_CONNECTION", "MARKETPLACE_DIAGNOSTICS_RUN", connection.id, metadata={"provider": PROVIDER, "itemId": item_id})
        self.db.commit(); self.db.refresh(connection)
        return connection

    def item_details_capability(self) -> MarketplaceCapability | None:
        return self.db.scalar(select(MarketplaceCapability).where(
            MarketplaceCapability.provider == PROVIDER,
            MarketplaceCapability.capability_key == "ITEM_DETAILS"))

    def item_details_probe(self, item_id: str) -> dict | None:
        row = self.item_details_capability()
        if row is None:
            return None
        metadata = row.metadata_ or {}
        probe = (metadata.get("itemProbes") or {}).get(item_id)
        if isinstance(probe, dict):
            return probe
        # Compatibility with rows written before item-scoped probes existed.
        if metadata.get("itemId") == item_id:
            return {"status": row.status, "httpStatus": row.last_http_status,
                    "reasonCode": row.reason_code, "checkedAt": row.checked_at.isoformat() if row.checked_at else None,
                    **{key: metadata[key] for key in ("remoteStatus", "remoteErrorCode", "remoteErrorType",
                                                       "remoteCauseCode", "remoteCauseType") if key in metadata}}
        return None

    def catalog_product_probe(self, catalog_product_id: str) -> dict | None:
        row = self.db.scalar(select(MarketplaceCapability).where(
            MarketplaceCapability.provider == PROVIDER,
            MarketplaceCapability.capability_key == "CATALOG_PRODUCT"))
        if row is None:
            return None
        metadata = row.metadata_ or {}
        probe = (metadata.get("catalogProductProbes") or {}).get(catalog_product_id)
        return probe if isinstance(probe, dict) else None

    def fetch_item_details(self, value: str) -> tuple[str, CapabilityResult]:
        """Single official ITEM_DETAILS path shared by diagnostics and refresh."""
        item_id = parse_item_id(value)
        if not item_id:
            raise ValueError("Informe um item ID MLB válido ou uma URL que contenha esse ID.")
        result = self.client.get("ITEM_DETAILS", f"/items/{item_id}", requires_auth=True)
        self._persist(result, {"itemId": item_id})
        return item_id, result

    def fetch_catalog_product(self, catalog_product_id: str) -> CapabilityResult:
        if not _normalized_item(catalog_product_id):
            raise ValueError("Informe um catalogProductId MLB válido.")
        result = self.client.get("CATALOG_PRODUCT", f"/products/{catalog_product_id}", requires_auth=True)
        self._persist(result, {"catalogProductId": catalog_product_id})
        return result

    def _persist(self, result: CapabilityResult, metadata: dict | None = None):
        row = self.db.scalar(select(MarketplaceCapability).where(MarketplaceCapability.provider == PROVIDER, MarketplaceCapability.capability_key == result.key))
        old_status = row.status if row else None
        if row is None:
            row = MarketplaceCapability(provider=PROVIDER, capability_key=result.key)
            self.db.add(row)
        item_id = (metadata or {}).get("itemId") if result.key == "ITEM_DETAILS" else None
        catalog_product_id = (metadata or {}).get("catalogProductId") if result.key == "CATALOG_PRODUCT" else None
        stored_metadata = dict(row.metadata_ or {})
        if item_id:
            probes = dict(stored_metadata.get("itemProbes") or {})
            probes.pop(item_id, None)
            probes[item_id] = {"status": result.status, "httpStatus": result.http_status,
                               "reasonCode": result.reason_code, "checkedAt": utcnow().isoformat(),
                               **result.metadata}
            while len(probes) > 20:
                probes.pop(next(iter(probes)))
            stored_metadata["itemProbes"] = probes
            aggregate_status = "AVAILABLE" if any(probe.get("status") == "AVAILABLE" for probe in probes.values()) else result.status
        elif catalog_product_id:
            probes = dict(stored_metadata.get("catalogProductProbes") or {})
            probes.pop(catalog_product_id, None)
            probes[catalog_product_id] = {"status": result.status, "httpStatus": result.http_status,
                                          "reasonCode": result.reason_code, "checkedAt": utcnow().isoformat(),
                                          **result.metadata}
            while len(probes) > 20:
                probes.pop(next(iter(probes)))
            stored_metadata["catalogProductProbes"] = probes
            aggregate_status = "AVAILABLE" if any(probe.get("status") == "AVAILABLE" for probe in probes.values()) else result.status
        else:
            aggregate_status = result.status
        row.status = aggregate_status; row.endpoint = result.endpoint; row.http_method = "GET" if result.endpoint else None
        row.last_http_status = result.http_status; row.latency_ms = result.latency_ms; row.reason_code = result.reason_code
        row.message = result.message; row.metadata_ = {**stored_metadata, **result.metadata, **(metadata or {})}; row.checked_at = utcnow(); row.updated_at = utcnow()
        if old_status is not None and old_status != aggregate_status:
            log_decision(self.db, "SYSTEM", "MARKETPLACE_CAPABILITY", "MARKETPLACE_CAPABILITY_CHANGED", row.id, metadata={"provider": PROVIDER, "capabilityKey": result.key, "from": old_status, "to": aggregate_status})
            statuses = {r.capability_key:r.status for r in self.db.scalars(select(MarketplaceCapability).where(MarketplaceCapability.provider == PROVIDER))}
            statuses[result.key] = aggregate_status
            discovery_lost = result.key in DISCOVERY and not any(statuses.get(key) == "AVAILABLE" for key in DISCOVERY)
            if (result.key in FOUNDATIONS or discovery_lost) and old_status == "AVAILABLE" and aggregate_status != "AVAILABLE":
                notify(self.db, "WARNING", "Capacidade essencial indisponível", f"{result.key} mudou de {old_status} para {aggregate_status}.", "MARKETPLACE")

    def _finish_connection(self, connection: MarketplaceConnection):
        rows = {r.capability_key: r.status for r in self.db.scalars(select(MarketplaceCapability).where(MarketplaceCapability.provider == PROVIDER))}
        basics = rows.get("CATEGORIES") == "AVAILABLE" and rows.get("SITE") == "AVAILABLE"
        discovery = rows.get("TRENDS_GLOBAL") == "AVAILABLE" or rows.get("TRENDS_CATEGORY") == "AVAILABLE" or rows.get("HIGHLIGHTS_CATEGORY") == "AVAILABLE"
        previous = connection.status
        if basics and discovery:
            connection.status = "AVAILABLE"
        elif basics:
            connection.status = "DEGRADED"
        else:
            connection.status = "UNAVAILABLE"
        now = utcnow(); connection.last_checked_at = now; connection.updated_at = now
        if connection.status == "AVAILABLE": connection.last_success_at = now
        if previous == "AVAILABLE" and connection.status == "UNAVAILABLE":
            notify(self.db, "CRITICAL", "Mercado Livre indisponível", "As capacidades oficiais básicas deixaram de responder.", "MARKETPLACE")
