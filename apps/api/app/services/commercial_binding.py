from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.models import CuratorCandidate, CuratorEvidence
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.integrations.mercado_livre.diagnostics import PROVIDER, parse_item_reference
from apps.api.app.integrations.mercado_livre.oauth import MercadoLivreTokenManager
from apps.api.app.services.curator import refresh
from apps.api.app.services.operations import log_decision


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _latest(db: Session, candidate_id: str, evidence_type: str) -> CuratorEvidence | None:
    return db.scalar(select(CuratorEvidence).where(
        CuratorEvidence.candidate_id == candidate_id,
        CuratorEvidence.evidence_type == evidence_type,
    ).order_by(CuratorEvidence.observed_at.desc()))


def _catalog_id(candidate: CuratorCandidate, binding: dict) -> str | None:
    return binding.get("catalogProductId") or (candidate.external_id if candidate.entity_type == "PRODUCT" else None)


class CommercialBindingService:
    """Explicit commercial offer binding. It never discovers third-party offers."""

    def __init__(self, db: Session, client: MercadoLivreClient | None = None):
        self.db = db
        self.client = client or MercadoLivreClient(token_manager=MercadoLivreTokenManager(db))
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def current(self, candidate_id: str) -> dict:
        candidate = self._candidate(candidate_id)
        row = _latest(self.db, candidate.id, "MARKETPLACE_LISTING_BINDING")
        binding = dict(row.value_json or {}) if row else {}
        affiliate = self._affiliate(candidate.id)
        return self._public(candidate, binding, affiliate)

    def bind(self, candidate_id: str, source: str, *, confirm_mismatch: bool = False) -> dict:
        candidate = self._candidate(candidate_id)
        reference = parse_item_reference(source)
        if not reference.source_item_id:
            if reference.catalog_product_id:
                raise ValueError("CATALOG_PRODUCT_WITHOUT_OFFER")
            raise ValueError("MARKETPLACE_ITEM_INVALID")

        current = _latest(self.db, candidate.id, "MARKETPLACE_LISTING_BINDING")
        previous = dict(current.value_json or {}) if current else {}
        catalog_product_id = _catalog_id(candidate, previous) or reference.catalog_product_id
        validation, observed = self._validate(reference.source_item_id)
        observed_catalog = observed.get("catalogProductId")
        match = "UNKNOWN"
        if catalog_product_id and observed_catalog:
            match = "MATCHED" if catalog_product_id == observed_catalog else "MISMATCH"
        if match == "MISMATCH" and not confirm_mismatch:
            raise ValueError("CATALOG_PRODUCT_MISMATCH_CONFIRMATION_REQUIRED")

        action = "COMMERCIAL_BINDING_UPDATED" if current else "COMMERCIAL_BINDING_CREATED"
        value = {
            "itemId": reference.source_item_id,
            "sourceItemId": reference.source_item_id,
            "catalogProductId": catalog_product_id,
            "originalUrl": source if "://" in source else None,
            "resolutionMethod": reference.resolution_method,
            "validationStatus": validation["status"],
            "validationReasonCode": validation.get("reasonCode"),
            "catalogMatchStatus": match,
            "observed": observed,
        }
        if current is None:
            current = CuratorEvidence(candidate_id=candidate.id, evidence_type="MARKETPLACE_LISTING_BINDING",
                source_kind="MANUAL_OPERATOR", source_name="Oferta informada pelo operador",
                source_reference=reference.source_item_id, confidence="HIGH", verification_status="UNVERIFIED")
            self.db.add(current)
        current.value_json = value
        current.source_reference = reference.source_item_id
        current.verification_status = "VERIFIED" if validation["status"] == "VALIDATED" else "UNVERIFIED"
        current.observed_at = _now()
        current.updated_at = _now()
        candidate.updated_at = _now()
        log_decision(self.db, "OPERATOR", "CURATOR_CANDIDATE", action, candidate.id,
            metadata={"candidateId": candidate.id, "catalogProductId": catalog_product_id,
                      "sourceItemId": reference.source_item_id, "validationStatus": validation["status"],
                      "catalogMatchStatus": match, "resolutionMethod": reference.resolution_method})
        if validation["status"] == "VALIDATED":
            log_decision(self.db, "SYSTEM", "CURATOR_CANDIDATE", "COMMERCIAL_BINDING_VALIDATED", candidate.id,
                metadata={"candidateId": candidate.id, "sourceItemId": reference.source_item_id,
                          "catalogMatchStatus": match})
        if match == "MISMATCH":
            log_decision(self.db, "OPERATOR", "CURATOR_CANDIDATE", "COMMERCIAL_BINDING_MISMATCH", candidate.id,
                metadata={"candidateId": candidate.id, "catalogProductId": catalog_product_id,
                          "sourceItemId": reference.source_item_id})
        self.db.commit()
        return self._public(candidate, value, self._affiliate(candidate.id))

    def remove(self, candidate_id: str) -> None:
        candidate = self._candidate(candidate_id)
        row = _latest(self.db, candidate.id, "MARKETPLACE_LISTING_BINDING")
        if row:
            # Capture the binding provenance before deleting its evidence row.
            # Legacy commercial snapshots may only carry these identifiers in
            # their value JSON, so the closure must happen first.
            binding = dict(row.value_json or {})
            source_item_id = binding.get("sourceItemId") or binding.get("itemId")
            closed_count = self._close_commercial_evidence(candidate, source_item_id, binding)
            # Persist the historical boundary before the binding disappears and
            # before refresh() issues its evidence query in this transaction.
            self.db.flush()
            refresh(self.db, candidate)
            self.db.delete(row)
            log_decision(self.db, "OPERATOR", "CURATOR_CANDIDATE", "COMMERCIAL_BINDING_REMOVED", candidate.id,
                metadata={"candidateId": candidate.id, "sourceItemId": source_item_id,
                          "commercialEvidenceClosedCount": closed_count})
            self.db.commit()

    def _close_commercial_evidence(self, candidate: CuratorCandidate, source_item_id: str | None, binding: dict) -> int:
        if not source_item_id:
            return 0
        observed = binding.get("observed") if isinstance(binding.get("observed"), dict) else {}
        observed_seller_id = str(
            observed.get("sellerId")
            or binding.get("observedSellerId")
            or binding.get("sellerId")
            or ""
        ) or None
        rows = self.db.scalars(select(CuratorEvidence).where(
            CuratorEvidence.candidate_id == candidate.id,
            CuratorEvidence.evidence_type.in_(("CURRENT_PRICE", "REVIEW_SUMMARY", "SELLER_REPUTATION")),
            CuratorEvidence.valid_until.is_(None),
        )).all()
        closed = 0
        for evidence in rows:
            value = dict(evidence.value_json or {})
            metadata = dict(evidence.metadata_ or {})
            # New snapshots carry sourceItemId in metadata.  Old F2.5 records
            # used observedItemId (price) or itemId (reviews) in valueJson.
            item_ids = {
                str(item_id) for item_id in (
                    metadata.get("sourceItemId"),
                    value.get("sourceItemId"),
                    value.get("observedItemId"),
                    value.get("itemId"),
                ) if item_id is not None and str(item_id)
            }
            is_bound_item = source_item_id in item_ids
            is_legacy_seller = (
                evidence.evidence_type == "SELLER_REPUTATION"
                and not item_ids
                and observed_seller_id is not None
                and str(value.get("sellerId") or "") == observed_seller_id
                and evidence.source_kind == "MERCADO_LIVRE_OFFICIAL_API"
            )
            if is_bound_item or is_legacy_seller:
                evidence.valid_until = _now()
                evidence.updated_at = _now()
                closed += 1
        return closed

    def set_affiliate_url(self, candidate_id: str, affiliate_url: str, *, confirm_replace: bool = False) -> dict:
        candidate = self._candidate(candidate_id)
        value = affiliate_url.strip()
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("AFFILIATE_URL_INVALID")
        existing = _latest(self.db, candidate.id, "AFFILIATE_DESTINATION")
        existing_value = dict(existing.value_json or {}) if existing else {}
        if existing_value.get("affiliateUrl") and existing_value.get("affiliateUrl") != value and not confirm_replace:
            raise ValueError("AFFILIATE_URL_REPLACEMENT_CONFIRMATION_REQUIRED")
        if existing is None:
            existing = CuratorEvidence(candidate_id=candidate.id, evidence_type="AFFILIATE_DESTINATION",
                source_kind="MANUAL_OPERATOR", source_name="Link afiliado informado pelo operador",
                source_reference=sha256(value.encode("utf-8")).hexdigest()[:24], confidence="HIGH")
            self.db.add(existing)
        existing.value_json = {"affiliateUrl": value, "affiliateUrlSource": "MANUAL_OPERATOR",
                               "affiliateValidationStatus": "FORMAT_VALID", "destinationUrl": None,
                               "destinationStrategy": "UNKNOWN", "failureCode": None}
        existing.verification_status = "UNVERIFIED"
        existing.observed_at = _now()
        existing.updated_at = _now()
        log_decision(self.db, "OPERATOR", "CURATOR_CANDIDATE", "AFFILIATE_URL_PROVIDED", candidate.id,
            metadata={"candidateId": candidate.id, "urlPresent": True, "status": "FORMAT_VALID"})
        self.db.commit()
        binding_row = _latest(self.db, candidate.id, "MARKETPLACE_LISTING_BINDING")
        binding = dict(binding_row.value_json or {}) if binding_row else {}
        return self._public(candidate, binding, self._affiliate(candidate.id))

    def _validate(self, item_id: str) -> tuple[dict, dict]:
        result = self.client.get("ITEM_DETAILS", f"/items/{item_id}", requires_auth=True)
        if result.status == "AVAILABLE" and isinstance(result.data, dict):
            item = result.data
            return ({"status": "VALIDATED", "reasonCode": None}, {
                "title": item.get("title"), "catalogProductId": item.get("catalog_product_id"),
                "sellerId": item.get("seller_id"), "price": item.get("price"),
                "currencyId": item.get("currency_id"), "availableQuantity": item.get("available_quantity"),
                "permalink": item.get("permalink"), "status": item.get("status"), "condition": item.get("condition"),
            })
        if result.http_status == 404:
            return ({"status": "INVALID", "reasonCode": "NOT_FOUND"}, {})
        if result.status == "FORBIDDEN" or result.http_status == 403:
            return ({"status": "UNVERIFIED", "reasonCode": "FORBIDDEN"}, {})
        return ({"status": "UNKNOWN", "reasonCode": result.reason_code or "VALIDATION_FAILED"}, {})

    def _candidate(self, candidate_id: str) -> CuratorCandidate:
        candidate = self.db.get(CuratorCandidate, candidate_id)
        if not candidate:
            raise ValueError("CANDIDATE_NOT_FOUND")
        return candidate

    def _affiliate(self, candidate_id: str) -> dict:
        row = _latest(self.db, candidate_id, "AFFILIATE_DESTINATION")
        value = dict(row.value_json or {}) if row else {}
        status = value.get("affiliateValidationStatus") or ("PROVIDED" if value.get("affiliateUrl") else "NOT_SET")
        return {"status": status, "urlPresent": bool(value.get("affiliateUrl")), "url": value.get("affiliateUrl")}

    def _public(self, candidate: CuratorCandidate, binding: dict, affiliate: dict) -> dict:
        observed = dict(binding.get("observed") or {})
        raw_status = binding.get("validationStatus") or binding.get("itemDetailsStatus")
        validation_status = "UNVERIFIED" if raw_status == "FORBIDDEN" else raw_status or "NOT_SET"
        validation_reason = binding.get("validationReasonCode") or ("FORBIDDEN" if raw_status == "FORBIDDEN" else None)
        return {"candidateId": candidate.id, "catalogProductId": _catalog_id(candidate, binding),
                "sourceItemId": binding.get("sourceItemId") or binding.get("itemId"),
                "originalUrl": binding.get("originalUrl"), "validationStatus": validation_status,
                "validationReasonCode": validation_reason,
                "catalogMatchStatus": binding.get("catalogMatchStatus") or "UNKNOWN", "observed": observed,
                "affiliate": affiliate}
