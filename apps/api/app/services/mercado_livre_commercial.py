from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence, MarketplaceCapability
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.integrations.mercado_livre.oauth import MercadoLivreTokenManager
from apps.api.app.integrations.mercado_livre.diagnostics import PROVIDER, MercadoLivreDiagnostics, parse_item_id, parse_item_reference
from apps.api.app.services.operations import log_decision


OFFICIAL_SOURCE = "MERCADO_LIVRE_OFFICIAL_API"
AFFILIATE_SOURCE = "MANUAL_OFFICIAL_TOOL"
AFFILIATE_HOSTS = ("mercadolivre.com.br", "mercadolibre.com", "meli.la")


def _now():
    return datetime.now(timezone.utc)


def _latest_binding(db: Session, candidate_id: str) -> tuple[CuratorEvidence | None, dict]:
    row = db.scalar(select(CuratorEvidence).where(
        CuratorEvidence.candidate_id == candidate_id,
        CuratorEvidence.evidence_type == "MARKETPLACE_LISTING_BINDING",
    ).order_by(CuratorEvidence.observed_at.desc()))
    return row, dict(row.value_json or {}) if row else {}


class MarketplaceListingBindingService:
    def __init__(self, db: Session):
        self.db = db

    def bind(self, candidate_id: str, source: str) -> dict:
        candidate = self.db.get(CuratorCandidate, candidate_id)
        if not candidate:
            raise ValueError("CANDIDATE_NOT_FOUND")
        reference = parse_item_reference(source)
        source_item_id = reference.source_item_id
        catalog_product_id = reference.catalog_product_id
        primary_id = catalog_product_id or source_item_id
        if not primary_id:
            raise ValueError("MARKETPLACE_ITEM_INVALID")
        candidate.provider = PROVIDER
        candidate.site_id = settings.meli_site_id or "MLB"
        candidate.entity_type = "PRODUCT" if catalog_product_id else "ITEM"
        candidate.external_id = primary_id
        candidate.source_url = source if "://" in source else None
        candidate.updated_at = _now()
        binding = self.db.scalar(select(CuratorEvidence).where(CuratorEvidence.candidate_id == candidate.id,
            CuratorEvidence.evidence_type == "MARKETPLACE_LISTING_BINDING",
            CuratorEvidence.source_reference == primary_id))
        if binding is None:
            binding = CuratorEvidence(candidate_id=candidate.id,evidence_type="MARKETPLACE_LISTING_BINDING",
                source_kind="MANUAL_OPERATOR",source_name="Binding informado pelo operador",source_reference=primary_id,
                confidence="HIGH",verification_status="VERIFIED")
            self.db.add(binding)
        binding.value_json={"itemId":source_item_id,"sourceItemId":source_item_id,"catalogProductId":catalog_product_id,
                            "sourcePermalink":candidate.source_url,"resolutionMethod":reference.resolution_method}
        binding.observed_at=_now();binding.updated_at=_now()
        log_decision(self.db, "OPERATOR", "CURATOR_CANDIDATE", "MARKETPLACE_LISTING_BOUND", candidate.id,
                     metadata={"provider": PROVIDER, "siteId": candidate.site_id, "sourceItemId": source_item_id,
                               "catalogProductId": catalog_product_id,
                               "resolutionMethod": reference.resolution_method})
        self.db.commit()
        return {"candidateId": candidate.id, "provider": candidate.provider, "siteId": candidate.site_id,
                "itemId": source_item_id, "sourceItemId":source_item_id,"catalogProductId":catalog_product_id,
                "externalId":candidate.external_id,"entityType":candidate.entity_type,
                "sourcePermalink": candidate.source_url,
                "observedAt": candidate.updated_at}


class MarketplaceRefreshService:
    def __init__(self, db: Session, client: MercadoLivreClient | None = None):
        self.db = db
        self.client = client or MercadoLivreClient(token_manager=MercadoLivreTokenManager(db))
        self._owns_client = client is None

    def close(self):
        if self._owns_client:
            self.client.close()

    def refresh(self, candidate_id: str, source: str | None = None) -> dict:
        candidate = self.db.get(CuratorCandidate, candidate_id)
        if not candidate:
            raise ValueError("CANDIDATE_NOT_FOUND")
        if source:
            MarketplaceListingBindingService(self.db).bind(candidate_id, source)
            candidate = self.db.get(CuratorCandidate, candidate_id)
        if candidate.provider != PROVIDER or not candidate.external_id:
            raise ValueError("MARKETPLACE_LISTING_NOT_BOUND")
        diagnostics = MercadoLivreDiagnostics(self.db, self.client)
        binding_row,binding = _latest_binding(self.db,candidate.id)
        source_item_id = binding.get("sourceItemId") or binding.get("itemId") or (candidate.external_id if candidate.entity_type == "ITEM" else None)
        catalog_product_id = binding.get("catalogProductId") or (candidate.external_id if candidate.entity_type == "PRODUCT" else None)
        catalog_result = diagnostics.fetch_catalog_product(catalog_product_id) if catalog_product_id else None
        catalog = catalog_result.data if catalog_result and catalog_result.status == "AVAILABLE" and isinstance(catalog_result.data,dict) else None
        item_probe = diagnostics.item_details_probe(source_item_id) if source_item_id else None
        item_result = None
        if source_item_id and item_probe and item_probe.get("status") == "AVAILABLE":
            resolved_item_id,item_result = diagnostics.fetch_item_details(source_item_id)
            if resolved_item_id != source_item_id: raise ValueError("MARKETPLACE_BINDING_MISMATCH")
        item = item_result.data if item_result and item_result.status == "AVAILABLE" and isinstance(item_result.data,dict) else None
        item_status = item_result.status if item_result else item_probe.get("status") if item_probe else "UNKNOWN"
        catalog_status = catalog_result.status if catalog_result else "NOT_APPLICABLE"
        if not catalog and not item:
            if not catalog_product_id:
                log_decision(self.db,"SYSTEM","CURATOR_CANDIDATE","MARKETPLACE_REFRESH_BLOCKED",candidate.id,
                    metadata={"stage":"CAPABILITY_CHECK","capability":"ITEM_DETAILS","capabilityStatus":item_status,
                              "provider":PROVIDER,"siteId":candidate.site_id,"itemId":source_item_id,
                              **{key:item_probe[key] for key in ("remoteStatus","remoteErrorCode","remoteErrorType",
                                                                 "remoteCauseCode","remoteCauseType") if item_probe and key in item_probe}})
                self.db.commit();raise ValueError("ITEM_DETAILS_UNAVAILABLE")
            log_decision(self.db,"SYSTEM","CURATOR_CANDIDATE","MARKETPLACE_REFRESH_BLOCKED",candidate.id,
                metadata={"stage":"PRODUCT_CAPABILITY_CHECK","provider":PROVIDER,"siteId":candidate.site_id,
                          "sourceItemId":source_item_id,"catalogProductId":catalog_product_id,
                          "itemDetailsStatus":item_status,"catalogProductStatus":catalog_status})
            self.db.commit();raise ValueError("PRODUCT_DETAILS_UNAVAILABLE")
        description = None
        description_capability = self.db.scalar(select(MarketplaceCapability).where(
            MarketplaceCapability.provider == PROVIDER,
            MarketplaceCapability.capability_key == "ITEM_DESCRIPTION"))
        if item and source_item_id and description_capability and description_capability.status == "AVAILABLE":
            description_result = self.client.get("ITEM_DESCRIPTION", f"/items/{source_item_id}/description", requires_auth=True)
            if description_result.status == "AVAILABLE" and isinstance(description_result.data, dict):
                description = description_result.data
        candidate.working_title = (item or {}).get("title") or (catalog or {}).get("name") or candidate.working_title
        candidate.last_seen_at = _now()
        if catalog:self._catalog_evidence(candidate,catalog,catalog_product_id)
        if item:self._evidence(candidate,item,description)
        if binding_row:
            binding_row.value_json={**binding,"sourceItemId":source_item_id,"itemId":source_item_id,
                                    "catalogProductId":catalog_product_id,"itemDetailsStatus":item_status,
                                    "catalogProductStatus":catalog_status,"commercialCompleteness":"AVAILABLE" if item else "UNAVAILABLE"}
            binding_row.updated_at=_now()
        log_decision(self.db, "OPERATOR", "CURATOR_CANDIDATE", "MARKETPLACE_LISTING_REFRESHED", candidate.id,
                     metadata={"provider": PROVIDER,"siteId":candidate.site_id,"sourceItemId":source_item_id,
                               "catalogProductId":catalog_product_id,"itemDetailsStatus":item_status,
                               "catalogProductStatus":catalog_status,"commercialCompleteness":"AVAILABLE" if item else "UNAVAILABLE"})
        self.db.commit()
        return {"candidateId": candidate.id, "provider": PROVIDER, "siteId": candidate.site_id,
                "itemId":source_item_id,"sourceItemId":source_item_id,"catalogProductId":catalog_product_id,
                "externalId":candidate.external_id,"sourcePermalink":candidate.source_url,
                "title":(item or {}).get("title") or (catalog or {}).get("name"),
                "price":(item or {}).get("price"),"originalPrice":(item or {}).get("original_price"),
                "currency":(item or {}).get("currency_id"),"pictures":(item or {}).get("pictures") or (catalog or {}).get("pictures") or [],
                "attributes":(item or {}).get("attributes") or (catalog or {}).get("attributes") or [],"description":description,
                "itemDetailsStatus":item_status,"catalogProductStatus":catalog_status,
                "commercialCompleteness":"AVAILABLE" if item else "UNAVAILABLE"}

    def _catalog_evidence(self,candidate:CuratorCandidate,catalog:dict,catalog_product_id:str):
        reference=str(catalog.get("id") or catalog_product_id)
        if catalog.get("name"):
            self._upsert(candidate,"CATALOG_TITLE",value_text=str(catalog["name"]),reference=reference)
        for position,picture in enumerate(catalog.get("pictures") or []):
            if isinstance(picture,dict) and (picture.get("secure_url") or picture.get("url")):
                self._upsert(candidate,"CATALOG_PICTURE",value_json={**picture,"position":position,"provenance":OFFICIAL_SOURCE},reference=f"{reference}:{picture.get('id') or position}")
        for attr in catalog.get("attributes") or []:
            if isinstance(attr,dict) and (attr.get("value_name") or attr.get("value_id")):
                self._upsert(candidate,"CATALOG_ATTRIBUTE",value_json=attr,reference=f"{reference}:{attr.get('id') or attr.get('name')}",metadata={"attributeKey":attr.get("id"),"label":attr.get("name")})
        self._upsert(candidate,"CATALOG_DATA",value_json={key:catalog.get(key) for key in ("status","domain_id","parent_id") if catalog.get(key) is not None},reference=reference)

    def _evidence(self, candidate: CuratorCandidate, item: dict, description: dict | None):
        reference = str(item.get("id") or candidate.external_id)
        if item.get("title"):
            self._upsert(candidate, "LISTING_TITLE", value_text=str(item["title"]), reference=reference)
        if isinstance(item.get("price"), (int, float)):
            self._upsert(candidate, "CURRENT_PRICE", value_cents=round(float(item["price"]) * 100), reference=reference,
                         metadata={"currency": item.get("currency_id"), "fingerprint": self._fingerprint(item.get("price"))})
        original = item.get("original_price")
        if isinstance(original, (int, float)) and isinstance(item.get("price"), (int, float)) and float(original) > float(item["price"]):
            self._upsert(candidate, "PRICE_REFERENCE", value_cents=round(float(original) * 100), reference=reference,
                         metadata={"semantic": "ORIGINAL_PRICE", "currency": item.get("currency_id")})
        for attr in item.get("attributes") or []:
            if isinstance(attr, dict) and (attr.get("value_name") or attr.get("value_id")):
                self._upsert(candidate, "ATTRIBUTE", value_json=attr, reference=f"{reference}:{attr.get('id') or attr.get('name')}",
                             metadata={"attributeKey": attr.get("id"), "label": attr.get("name")})
        for position, picture in enumerate(item.get("pictures") or []):
            if isinstance(picture, dict) and (picture.get("secure_url") or picture.get("url")):
                payload = {**picture, "position": position, "provenance": OFFICIAL_SOURCE}
                self._upsert(candidate, "LISTING_PICTURE", value_json=payload,
                             reference=f"{reference}:{picture.get('id') or position}")
        listing = {key: item.get(key) for key in ("category_id", "sale_terms", "available_quantity", "sold_quantity",
            "condition", "catalog_product_id", "official_store_id", "seller_id", "shipping", "seller_address")
            if item.get(key) is not None}
        self._upsert(candidate, "LISTING_DATA", value_json=listing, reference=reference)
        if description and isinstance(description.get("plain_text"), str) and description["plain_text"].strip():
            self._upsert(candidate, "DESCRIPTION", value_text=description["plain_text"].strip(), reference=reference,
                         metadata={"dateCreated": description.get("date_created"), "lastUpdated": description.get("last_updated")})

    @staticmethod
    def _fingerprint(value) -> str:
        return sha256(str(value).encode("utf-8")).hexdigest()[:16]

    def _upsert(self, candidate, evidence_type, reference, value_text=None, value_cents=None, value_json=None, metadata=None):
        value_fingerprint = self._fingerprint({"text": value_text, "cents": value_cents, "json": value_json})
        rows = self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id == candidate.id,
                                                               CuratorEvidence.evidence_type == evidence_type,
                                                               CuratorEvidence.source_kind == OFFICIAL_SOURCE,
                                                               CuratorEvidence.source_reference == reference)).all()
        row = next((item for item in rows if (item.metadata_ or {}).get("valueFingerprint") == value_fingerprint), None)
        row = row or CuratorEvidence(candidate_id=candidate.id, evidence_type=evidence_type,
            source_kind=OFFICIAL_SOURCE, source_name="Mercado Livre API", source_reference=reference,
            confidence="HIGH", verification_status="VERIFIED")
        if row not in rows: self.db.add(row)
        row.value_text = value_text; row.value_cents = value_cents; row.value_json = value_json
        row.metadata_ = {**(metadata or {}), "valueFingerprint": value_fingerprint}; row.observed_at = _now(); row.updated_at = _now()


class AffiliateDestinationValidator:
    @staticmethod
    def validate(value: str | None, item_id: str | None, *, official: bool = False,
                 strategy: str = "UNKNOWN", destination_url: str | None = None) -> dict:
        if not value:
            return {"status": "UNKNOWN", "reasonCode": "AFFILIATE_URL_REQUIRED"}
        try:
            parts = urlsplit(value)
        except ValueError:
            return {"status": "INVALID", "reasonCode": "AFFILIATE_URL_INVALID"}
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return {"status": "INVALID", "reasonCode": "AFFILIATE_URL_INVALID"}
        if not official:
            return {"status": "UNKNOWN", "reasonCode": "AFFILIATE_SOURCE_NOT_HOMOLOGATED"}
        parsed = parse_item_id(value)
        valid_strategies = {"DIRECT_AFFILIATE_LINK", "LINK_IN_BIO_TO_AFFILIATE", "OWNED_LANDING_PAGE_TO_AFFILIATE"}
        if item_id and parsed and parsed == item_id and strategy in valid_strategies and destination_url:
            return {"status": "READY", "reasonCode": None}
        return {"status": "UNKNOWN", "reasonCode": "AFFILIATE_ITEM_ASSOCIATION_UNKNOWN"}


class AffiliateLinkResolver:
    """Resolve somente redirects HTTPS em hosts Mercado Livre permitidos; nunca lê HTML."""

    def __init__(self, client: httpx.Client | None = None, dns_resolver=None, max_redirects: int = 5):
        self.client = client or httpx.Client(timeout=5.0, follow_redirects=False,
                                             headers={"User-Agent": "AffiliateEngine/0.2 affiliate-validation"})
        self._owns_client = client is None
        self.dns_resolver = dns_resolver or socket.getaddrinfo
        self.max_redirects = max_redirects

    def close(self):
        if self._owns_client:
            self.client.close()

    @staticmethod
    def _allowed_host(host: str) -> bool:
        host = host.lower().rstrip(".")
        return any(host == allowed or host.endswith(f".{allowed}") for allowed in AFFILIATE_HOSTS)

    def _validate_target(self, value: str) -> tuple[bool, str | None]:
        try: parts = urlsplit(value)
        except ValueError: return False, "AFFILIATE_URL_INVALID"
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host or parts.username or parts.password:
            return False, "AFFILIATE_HTTPS_REQUIRED"
        if not self._allowed_host(host):
            return False, "AFFILIATE_HOST_NOT_ALLOWED"
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
            if not literal.is_global: return False, "AFFILIATE_PRIVATE_ADDRESS_BLOCKED"
        except ValueError:
            try: addresses = self.dns_resolver(host, 443, type=socket.SOCK_STREAM)
            except OSError: return False, "AFFILIATE_HOST_UNRESOLVED"
            for entry in addresses:
                try:
                    if not ipaddress.ip_address(entry[4][0]).is_global:
                        return False, "AFFILIATE_PRIVATE_ADDRESS_BLOCKED"
                except ValueError:
                    return False, "AFFILIATE_HOST_UNRESOLVED"
        return True, None

    def resolve(self, value: str) -> dict:
        current = value.strip()
        visited_hosts: list[str] = []
        for hop in range(self.max_redirects + 1):
            safe, reason = self._validate_target(current)
            if not safe: return {"status":"INVALID","finalUrl":None,"redirectCount":hop,"failureCode":reason,"visitedHosts":visited_hosts}
            visited_hosts.append((urlsplit(current).hostname or "").lower())
            try:
                response = self.client.request("HEAD", current, follow_redirects=False)
                if response.status_code == 405:
                    with self.client.stream("GET", current, headers={"Range":"bytes=0-0"}, follow_redirects=False) as streamed:
                        status_code, location = streamed.status_code, streamed.headers.get("location")
                else:
                    status_code, location = response.status_code, response.headers.get("location")
            except (httpx.TimeoutException, httpx.NetworkError):
                return {"status":"UNVERIFIED","finalUrl":None,"redirectCount":hop,"failureCode":"AFFILIATE_RESOLUTION_FAILED","visitedHosts":visited_hosts}
            if status_code in {301,302,303,307,308} and location:
                if hop >= self.max_redirects:
                    return {"status":"INVALID","finalUrl":None,"redirectCount":hop,"failureCode":"AFFILIATE_REDIRECT_LIMIT","visitedHosts":visited_hosts}
                current = urljoin(current, location);continue
            if 200 <= status_code < 400:
                return {"status":"RESOLVED","finalUrl":current,"redirectCount":hop,"failureCode":None,"visitedHosts":visited_hosts}
            return {"status":"UNVERIFIED","finalUrl":None,"redirectCount":hop,"failureCode":"AFFILIATE_REMOTE_UNAVAILABLE","visitedHosts":visited_hosts}
        return {"status":"INVALID","finalUrl":None,"redirectCount":self.max_redirects,"failureCode":"AFFILIATE_REDIRECT_LIMIT","visitedHosts":visited_hosts}


class AffiliateDestinationService:
    def __init__(self, db: Session, resolver: AffiliateLinkResolver | None = None):
        self.db = db;self.resolver = resolver or AffiliateLinkResolver();self._owns_resolver = resolver is None

    def close(self):
        if self._owns_resolver:self.resolver.close()

    def current(self, candidate_id: str) -> dict:
        candidate=self.db.get(CuratorCandidate,candidate_id)
        if not candidate:raise ValueError("CANDIDATE_NOT_FOUND")
        _,binding=_latest_binding(self.db,candidate.id);expected_item_id=binding.get("sourceItemId") or binding.get("itemId") or (candidate.external_id if candidate.entity_type=="ITEM" else None)
        row=self.db.scalar(select(CuratorEvidence).where(CuratorEvidence.candidate_id==candidate.id,
            CuratorEvidence.evidence_type=="AFFILIATE_DESTINATION").order_by(CuratorEvidence.observed_at.desc()))
        value=(row.value_json or {}) if row else {}
        return {"candidateId":candidate.id,"productTitle":candidate.working_title or candidate.source_display_text,
                "sourcePermalink":candidate.source_url,"expectedItemId":expected_item_id,
                "affiliateUrl":value.get("affiliateUrl"),"affiliateUrlSource":value.get("affiliateUrlSource"),
                "affiliateValidationStatus":value.get("affiliateValidationStatus") or "UNKNOWN",
                "affiliateItemId":value.get("affiliateItemId"),"destinationUrl":value.get("destinationUrl"),
                "destinationStrategy":value.get("destinationStrategy") or "UNKNOWN","failureCode":value.get("failureCode")}

    @staticmethod
    def _normalized(value: str) -> str:
        parts = urlsplit(value)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))

    @staticmethod
    def _disallowed_page(value: str) -> bool:
        parts = urlsplit(value);path = parts.path.lower().rstrip("/")
        if not path:return True
        blocked=("/search","/categor", "/ofertas", "/seller", "/vendedor", "/loja", "/perfil")
        return any(path.startswith(prefix) for prefix in blocked)

    def configure(self, candidate_id: str, affiliate_url: str, destination_strategy: str) -> dict:
        candidate = self.db.get(CuratorCandidate, candidate_id)
        if not candidate:raise ValueError("CANDIDATE_NOT_FOUND")
        if candidate.provider != PROVIDER or not candidate.external_id:raise ValueError("MARKETPLACE_LISTING_NOT_BOUND")
        _,binding=_latest_binding(self.db,candidate.id);expected_item_id=binding.get("sourceItemId") or binding.get("itemId") or (candidate.external_id if candidate.entity_type=="ITEM" else None)
        if not expected_item_id:raise ValueError("MARKETPLACE_SOURCE_ITEM_UNAVAILABLE")
        validation = self.resolver.resolve(affiliate_url)
        final_url = validation.get("finalUrl")
        failure = validation.get("failureCode")
        status = validation["status"]
        resolved_item = parse_item_id(final_url or "")
        if status == "RESOLVED" and (self._disallowed_page(affiliate_url) or self._disallowed_page(final_url or affiliate_url)):
            status, failure = "INVALID", "AFFILIATE_PAGE_NOT_ALLOWED"
        elif candidate.source_url and self._normalized(affiliate_url) == self._normalized(candidate.source_url):
            status, failure = "INVALID", "SOURCE_PERMALINK_REUSED"
        elif status == "RESOLVED" and resolved_item and resolved_item != expected_item_id:
            status, failure = "INVALID", "AFFILIATE_ITEM_MISMATCH"
        elif status == "RESOLVED" and resolved_item == expected_item_id:
            status, failure = "VALID", None
        elif status == "RESOLVED":
            status, failure = "UNVERIFIED", "AFFILIATE_ITEM_UNRESOLVED"
        destination_url = affiliate_url if status == "VALID" and destination_strategy == "DIRECT_AFFILIATE_LINK" else None
        now = _now();payload={"affiliateUrl":affiliate_url,"affiliateUrlSource":AFFILIATE_SOURCE,
            "expectedItemId":expected_item_id,"affiliateItemId":resolved_item,"affiliateValidationStatus":status,
            "validationMethod":"HTTPS_REDIRECT_ITEM_ID","validatedAt":now.isoformat(),"failureCode":failure,
            "destinationStrategy":destination_strategy,"destinationUrl":destination_url}
        fingerprint=self._fingerprint({"url":affiliate_url,"strategy":destination_strategy})
        rows=self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==candidate.id,
            CuratorEvidence.evidence_type=="AFFILIATE_DESTINATION",CuratorEvidence.source_kind==AFFILIATE_SOURCE)).all()
        row=next((x for x in rows if (x.metadata_ or {}).get("configurationFingerprint")==fingerprint),None)
        if row is None:
            row=CuratorEvidence(candidate_id=candidate.id,evidence_type="AFFILIATE_DESTINATION",source_kind=AFFILIATE_SOURCE,
                source_name="Ferramenta oficial informada pelo operador",source_reference=fingerprint,confidence="HIGH")
            self.db.add(row)
        row.value_json=payload;row.verification_status="VERIFIED" if status=="VALID" else "UNVERIFIED";row.observed_at=now;row.updated_at=now
        row.metadata_={"configurationFingerprint":fingerprint,"redirectCount":validation.get("redirectCount"),
                       "visitedHosts":validation.get("visitedHosts",[])}
        log_decision(self.db,"OPERATOR","CURATOR_CANDIDATE","AFFILIATE_DESTINATION_VALIDATED",candidate.id,
            metadata={"expectedItemId":expected_item_id,"resolvedItemId":resolved_item,"status":status,
                      "failureCode":failure,"destinationStrategy":destination_strategy})
        self.db.commit();return payload

    @staticmethod
    def _fingerprint(value) -> str:
        return sha256(str(value).encode("utf-8")).hexdigest()
