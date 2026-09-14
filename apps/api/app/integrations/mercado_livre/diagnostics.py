import re
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import MarketplaceCapability, MarketplaceConnection
from apps.api.app.services.operations import log_decision, notify
from .client import MercadoLivreClient
from .models import CapabilityResult

PROVIDER = "MERCADO_LIVRE"
CAPABILITY_KEYS = ["SITE", "CATEGORIES", "TRENDS_GLOBAL", "TRENDS_CATEGORY", "HIGHLIGHTS_CATEGORY", "MARKETPLACE_SEARCH", "AUTH_USER", "ITEM_DETAILS", "PRICE_DETAILS", "REVIEWS", "SELLER_DETAILS", "CATALOG_PRODUCT", "USER_PRODUCT"]
ESSENTIAL = {"SITE", "CATEGORIES", "TRENDS_GLOBAL", "TRENDS_CATEGORY", "HIGHLIGHTS_CATEGORY"}
ITEM_PATTERN = re.compile(r"(?<![A-Z0-9])(MLB-?\d{6,})(?!\d)", re.IGNORECASE)


def utcnow():
    return datetime.now(timezone.utc)


def parse_item_id(value: str) -> str | None:
    text = unquote(value.strip())
    if "://" in text:
        parsed = urlparse(text)
        hostname = parsed.hostname or ""
        allowed_host = any(hostname == domain or hostname.endswith(f".{domain}") for domain in ("mercadolivre.com.br", "mercadolibre.com"))
        if parsed.scheme not in {"http", "https"} or not allowed_host:
            return None
        text = f"{parsed.path} {parsed.query}"
    match = ITEM_PATTERN.search(text)
    return match.group(1).upper().replace("-", "") if match else None


class MercadoLivreDiagnostics:
    def __init__(self, db: Session, client: MercadoLivreClient | None = None):
        self.db = db
        self.client = client or MercadoLivreClient(settings.meli_access_token)
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
        return "ENV_ACCESS_TOKEN" if settings.meli_access_token else "ANONYMOUS"

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
        item_id = parse_item_id(value)
        if not item_id:
            raise ValueError("Informe um item ID MLB válido ou uma URL que contenha esse ID.")
        item = self.client.get("ITEM_DETAILS", f"/items/{item_id}")
        self._persist(item, {"itemId": item_id})
        if item.status != "AVAILABLE" or not isinstance(item.data, dict):
            for key in ["PRICE_DETAILS", "REVIEWS", "SELLER_DETAILS", "CATALOG_PRODUCT", "USER_PRODUCT"]:
                self._persist(CapabilityResult(key, "NOT_APPLICABLE", None, reason_code="ITEM_UNAVAILABLE", message="Depende de detalhes válidos do item."))
        else:
            data = item.data
            self._persist(self.client.get("PRICE_DETAILS", f"/items/{item_id}/sale_price", requires_auth=True), {"itemId": item_id})
            self._persist(self.client.get("REVIEWS", f"/reviews/item/{item_id}", requires_auth=True), {"itemId": item_id})
            seller_id = data.get("seller_id")
            self._persist(self.client.get("SELLER_DETAILS", f"/users/{seller_id}") if seller_id else CapabilityResult("SELLER_DETAILS", "NOT_APPLICABLE", None, reason_code="SELLER_ID_ABSENT", message="O item não informou seller_id."))
            catalog_id = data.get("catalog_product_id")
            self._persist(self.client.get("CATALOG_PRODUCT", f"/products/{catalog_id}") if catalog_id else CapabilityResult("CATALOG_PRODUCT", "NOT_APPLICABLE", None, reason_code="CATALOG_PRODUCT_ID_ABSENT", message="O item não está associado a produto de catálogo."))
            user_product_id = data.get("user_product_id")
            self._persist(self.client.get("USER_PRODUCT", f"/user-products/{user_product_id}", requires_auth=True) if user_product_id else CapabilityResult("USER_PRODUCT", "NOT_APPLICABLE", None, reason_code="USER_PRODUCT_ID_ABSENT", message="O item não informou user_product_id."))
        connection = self.connection(); self._finish_connection(connection)
        log_decision(self.db, "OPERATOR", "MARKETPLACE_CONNECTION", "MARKETPLACE_DIAGNOSTICS_RUN", connection.id, metadata={"provider": PROVIDER, "itemId": item_id})
        self.db.commit(); self.db.refresh(connection)
        return connection

    def _persist(self, result: CapabilityResult, metadata: dict | None = None):
        row = self.db.scalar(select(MarketplaceCapability).where(MarketplaceCapability.provider == PROVIDER, MarketplaceCapability.capability_key == result.key))
        old_status = row.status if row else None
        if row is None:
            row = MarketplaceCapability(provider=PROVIDER, capability_key=result.key)
            self.db.add(row)
        row.status = result.status; row.endpoint = result.endpoint; row.http_method = "GET" if result.endpoint else None
        row.last_http_status = result.http_status; row.latency_ms = result.latency_ms; row.reason_code = result.reason_code
        row.message = result.message; row.metadata_ = {**result.metadata, **(metadata or {})}; row.checked_at = utcnow(); row.updated_at = utcnow()
        if old_status is not None and old_status != result.status:
            log_decision(self.db, "SYSTEM", "MARKETPLACE_CAPABILITY", "MARKETPLACE_CAPABILITY_CHANGED", row.id, metadata={"provider": PROVIDER, "capabilityKey": result.key, "from": old_status, "to": result.status})
            if result.key in ESSENTIAL and old_status == "AVAILABLE" and result.status != "AVAILABLE":
                notify(self.db, "WARNING", "Capacidade essencial indisponível", f"{result.key} mudou de {old_status} para {result.status}.", "MARKETPLACE")

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
