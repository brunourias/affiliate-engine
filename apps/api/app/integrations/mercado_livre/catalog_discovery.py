from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence, RadarRun, RadarSignal
from apps.api.app.services.curator import refresh
from apps.api.app.services.operations import log_decision
from .client import MercadoLivreClient
from .catalog_discovery_policy import BLOCKED_POLICY, catalog_discovery_eligibility
from .catalog_discovery_relevance import DiscoveryRelevance, catalog_discovery_relevance
from .diagnostics import PROVIDER
from .oauth import MercadoLivreTokenManager

CATALOG_ID = re.compile(r"^MLB\d{6,}$", re.IGNORECASE)
SOURCE_KIND = "MERCADO_LIVRE_OFFICIAL_API"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CatalogDiscoveryError(ValueError):
    pass


class MercadoLivreCatalogDiscoveryService:
    """Resolve official Radar queries into deduplicated catalog PRODUCT candidates."""

    def __init__(self, db: Session, client: MercadoLivreClient | None = None):
        self.db = db
        self.client = client or MercadoLivreClient(token_manager=MercadoLivreTokenManager(db))
        self._owns_client = client is None
        self.site = settings.meli_site_id or "MLB"

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def resolve_run(self, run_id: str) -> dict[str, Any]:
        run = self.db.get(RadarRun, run_id)
        if not run or run.provider != PROVIDER:
            raise CatalogDiscoveryError("Execução do Radar não encontrada.")
        signals = list(self.db.scalars(select(RadarSignal).where(
            RadarSignal.radar_run_id == run.id,
            RadarSignal.entity_type == "QUERY",
        )))
        signals = self._ordered_signals(run, signals)
        summary = self._summary(run.id)
        summary["signalsAvailable"] = len(signals)
        log_decision(self.db, "OPERATOR", "RADAR_RUN", "CATALOG_DISCOVERY_STARTED", run.id,
                     metadata={"runId": run.id, "querySignals": len(signals), "status": "STARTED"})
        self.db.commit()
        eligible: list[tuple[RadarSignal, str]] = []
        for signal in signals:
            query = self._query(signal)
            if not query:
                summary["failures"].append({"signalId": signal.id, "reasonCode": "QUERY_EMPTY"})
                continue
            eligibility = catalog_discovery_eligibility(query)
            if eligibility.status == BLOCKED_POLICY:
                self._record_policy_block(signal, query, eligibility.reason_code, summary)
                continue
            eligible.append((signal, query))
        summary["signalsEligible"] = len(eligible)
        max_signals = max(1, settings.meli_catalog_discovery_max_signals_per_run)
        selected = eligible[:max_signals]
        summary["signalsSkippedByLimit"] = len(eligible) - len(selected)
        for signal, query in selected:
            self._resolve_allowed_signal(signal, query, summary)
        log_decision(self.db, "SYSTEM", "RADAR_RUN", "CATALOG_DISCOVERY_COMPLETED", run.id,
                     metadata={"runId": run.id, "signalsAvailable": summary["signalsAvailable"],
                               "signalsEligible": summary["signalsEligible"], "signalsProcessed": summary["signalsProcessed"],
                               "signalsSkippedByLimit": summary["signalsSkippedByLimit"], "policyBlockedCount": summary["policyBlockedCount"],
                               "productsFoundRaw": summary["productsFoundRaw"], "productsSelected": summary["productsSelected"],
                               "candidatesCreated": summary["candidatesCreated"],
                               "candidatesReused": summary["candidatesReused"], "evidenceAdded": summary["evidenceAdded"],
                               "failureCount": len(summary["failures"]), "status": "COMPLETED" if not summary["failures"] else "PARTIAL"})
        self.db.commit()
        return {"runId": run.id, **summary}

    def resolve_signal(self, signal_id: str) -> dict[str, Any]:
        signal = self.db.get(RadarSignal, signal_id)
        if not signal or signal.provider != PROVIDER:
            raise CatalogDiscoveryError("Sinal do Radar não encontrado.")
        summary = self._summary(signal.radar_run_id)
        summary["signalsAvailable"] = 1
        if signal.entity_type != "QUERY":
            summary["failures"].append({"signalId": signal.id, "reasonCode": "SIGNAL_NOT_QUERY"})
            return {"runId": signal.radar_run_id, **summary}
        self._resolve_signal(signal, summary)
        self.db.commit()
        return {"runId": signal.radar_run_id, **summary}

    @staticmethod
    def _summary(run_id: str) -> dict[str, Any]:
        return {"signalsAvailable": 0, "signalsEligible": 0, "signalsProcessed": 0, "signalsSkippedByLimit": 0,
                "productsFoundRaw": 0, "productsSelected": 0, "candidatesCreated": 0,
                "candidatesReused": 0, "evidenceAdded": 0, "candidateIds": [], "failures": [],
                "policyBlockedCount": 0, "policyBlocked": [], "selectedProducts": []}

    def _resolve_signal(self, signal: RadarSignal, summary: dict[str, Any]) -> None:
        query = self._query(signal)
        if not query:
            summary["failures"].append({"signalId": signal.id, "reasonCode": "QUERY_EMPTY"})
            return
        eligibility = catalog_discovery_eligibility(query)
        if eligibility.status == BLOCKED_POLICY:
            self._record_policy_block(signal, query, eligibility.reason_code, summary)
            return
        summary["signalsEligible"] = 1
        self._resolve_allowed_signal(signal, query, summary)

    @staticmethod
    def _query(signal: RadarSignal) -> str:
        return " ".join((signal.display_text or "").split())

    @staticmethod
    def _ordered_signals(run: RadarRun, signals: list[RadarSignal]) -> list[RadarSignal]:
        def key(signal: RadarSignal) -> tuple[int, int, str, str, str]:
            source_priority = 0
            if run.requested_category_id:
                source_priority = {"TREND_CATEGORY": 0, "TREND_GLOBAL": 1}.get(signal.source_type, 2)
            return (source_priority, signal.rank if signal.rank is not None else 1_000_000,
                    signal.source_type, signal.observed_at.isoformat(), signal.id)
        return sorted(signals, key=key)

    def _record_policy_block(self, signal: RadarSignal, query: str, reason_code: str | None, summary: dict[str, Any]) -> None:
        summary["policyBlockedCount"] += 1
        summary["policyBlocked"].append({"signalId": signal.id, "query": query, "status": BLOCKED_POLICY,
                                          "reasonCode": reason_code})
        log_decision(self.db, "SYSTEM", "RADAR_SIGNAL", "CATALOG_DISCOVERY_QUERY_BLOCKED_POLICY", signal.id,
                     metadata={"runId": signal.radar_run_id, "signalId": signal.id, "reasonCode": reason_code})

    def _resolve_allowed_signal(self, signal: RadarSignal, query: str, summary: dict[str, Any]) -> None:
        summary["signalsProcessed"] += 1
        result = self.client.get("CATALOG_PRODUCT_SEARCH", "/products/search", requires_auth=True,
                                 params={"site_id": self.site, "status": "active", "q": query})
        if result.status != "AVAILABLE":
            summary["failures"].append({"signalId": signal.id, "query": query, "reasonCode": result.reason_code,
                                        "httpStatus": result.http_status})
            return
        products = result.data if isinstance(result.data, list) else result.data.get("results", []) if isinstance(result.data, dict) else []
        valid = [item for item in products if self._valid_product(item)]
        summary["productsFoundRaw"] += len(valid)
        ranked = self._rank_products(query, valid)
        selected = ranked[:max(1, settings.meli_catalog_discovery_limit)]
        summary["productsSelected"] += len(selected)
        summary["selectedProducts"].append({"signalId": signal.id, "query": query, "selectedProducts": [
            {"catalogProductId": str(item["product"]["id"]).upper(), "title": self._product_title(item["product"]),
             "relevanceScore": item["relevance"].score, "originalPosition": item["originalPosition"],
             "selectedPosition": position, "reasons": list(item["relevance"].reasons)}
            for position, item in enumerate(selected, 1)
        ]})
        for position, ranked_product in enumerate(selected, 1):
            product = ranked_product["product"]
            catalog_id = str(product["id"]).upper()
            enriched = self.client.get("CATALOG_PRODUCT", f"/products/{catalog_id}", requires_auth=True)
            details = enriched.data if enriched.status == "AVAILABLE" and isinstance(enriched.data, dict) else None
            candidate, created = self._candidate(catalog_id, signal, product, details)
            summary["candidatesCreated" if created else "candidatesReused"] += 1
            if candidate.id not in summary["candidateIds"]:
                summary["candidateIds"].append(candidate.id)
            summary["evidenceAdded"] += self._market_signal(candidate, signal, query, position, ranked_product)
            if details:
                summary["evidenceAdded"] += self._catalog_evidence(candidate, catalog_id, details)
            elif enriched.status != "AVAILABLE":
                summary["failures"].append({"signalId": signal.id, "catalogProductId": catalog_id,
                                            "reasonCode": enriched.reason_code, "httpStatus": enriched.http_status})
            refresh(self.db, candidate)

    @staticmethod
    def _valid_product(product: Any) -> bool:
        return isinstance(product, dict) and isinstance(product.get("id"), str) and bool(CATALOG_ID.fullmatch(product["id"])) and str(product.get("status", "active")).lower() == "active"

    @staticmethod
    def _product_title(product: dict[str, Any]) -> str:
        return str(product.get("name") or product.get("title") or "")

    def _rank_products(self, query: str, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = [{"product": product, "originalPosition": position,
                   "relevance": catalog_discovery_relevance(query, self._product_title(product))}
                  for position, product in enumerate(products, 1)]
        return sorted(ranked, key=lambda item: (-item["relevance"].score, item["originalPosition"],
                                                 str(item["product"]["id"]).upper()))

    def _candidate(self, catalog_id: str, signal: RadarSignal, product: dict, details: dict | None) -> tuple[CuratorCandidate, bool]:
        candidate = self.db.scalar(select(CuratorCandidate).where(
            CuratorCandidate.provider == PROVIDER,
            CuratorCandidate.entity_type == "PRODUCT",
            CuratorCandidate.external_id == catalog_id,
        ))
        now = utcnow()
        title = (details or {}).get("name") or product.get("name") or product.get("title")
        if candidate:
            candidate.last_seen_at = now
            candidate.updated_at = now
            if title and not candidate.working_title:
                candidate.working_title = str(title)[:300]
            log_decision(self.db, "SYSTEM", "CURATOR_CANDIDATE", "CATALOG_PRODUCT_CANDIDATE_REUSED", candidate.id,
                         metadata={"catalogProductId": catalog_id, "signalId": signal.id, "runId": signal.radar_run_id})
            return candidate, False
        candidate = CuratorCandidate(provider=PROVIDER, site_id=self.site, source_type="CATALOG_DISCOVERY",
            source_radar_signal_id=signal.id, source_radar_run_id=signal.radar_run_id, entity_type="PRODUCT",
            external_id=catalog_id, category_external_id=signal.category_external_id,
            source_display_text=" ".join((signal.display_text or "").lower().split()),
            working_title=str(title)[:300] if title else None, first_seen_at=now, last_seen_at=now)
        self.db.add(candidate); self.db.flush()
        log_decision(self.db, "SYSTEM", "CURATOR_CANDIDATE", "CATALOG_PRODUCT_CANDIDATE_CREATED", candidate.id,
                     metadata={"catalogProductId": catalog_id, "signalId": signal.id, "runId": signal.radar_run_id})
        return candidate, True

    def _market_signal(self, candidate: CuratorCandidate, signal: RadarSignal, query: str, position: int,
                       ranked_product: dict[str, Any]) -> int:
        row = self.db.scalar(select(CuratorEvidence).where(CuratorEvidence.candidate_id == candidate.id,
            CuratorEvidence.evidence_type == "MARKET_SIGNAL", CuratorEvidence.source_reference == signal.id))
        if row:
            return 0
        self.db.add(CuratorEvidence(candidate_id=candidate.id, evidence_type="MARKET_SIGNAL", source_kind=SOURCE_KIND,
            source_name=signal.source_type, source_reference=signal.id, confidence="HIGH", verification_status="VERIFIED",
            observed_at=signal.observed_at, value_json={"sourceRadarSignalId": signal.id, "sourceRadarRunId": signal.radar_run_id,
                "sourceType": signal.source_type, "query": query, "radarRank": signal.rank,
                "catalogSearchPosition": position, "categoryExternalId": signal.category_external_id,
                "observedAt": signal.observed_at.isoformat(),
                "discoveryRelevanceScore": ranked_product["relevance"].score,
                "originalSearchPosition": ranked_product["originalPosition"], "selectedPosition": position,
                "discoveryRelevanceReasons": list(ranked_product["relevance"].reasons)}))
        return 1

    def _catalog_evidence(self, candidate: CuratorCandidate, catalog_id: str, details: dict) -> int:
        added = 0
        identity_ref = f"catalog:{catalog_id}:identity"
        if not self._exists(candidate.id, "IDENTITY", identity_ref):
            self.db.add(CuratorEvidence(candidate_id=candidate.id, evidence_type="IDENTITY", value_text=str(details.get("name") or catalog_id),
                value_json={"catalogProductId": catalog_id, "status": details.get("status"), "domainId": details.get("domain_id"), "parentId": details.get("parent_id")},
                source_kind=SOURCE_KIND, source_name="Catalog product", source_reference=identity_ref, confidence="HIGH", verification_status="VERIFIED")); added += 1
        technical_ref = f"catalog:{catalog_id}:technical"
        technical_data = {"catalogProductId": catalog_id, "domainId": details.get("domain_id"), "parentId": details.get("parent_id"),
                          "attributes": details.get("attributes") or [], "pictures": details.get("pictures") or [],
                          "officialCatalogData": details}
        technical = self.db.scalar(select(CuratorEvidence).where(CuratorEvidence.candidate_id == candidate.id,
            CuratorEvidence.evidence_type == "TECHNICAL_SPEC", CuratorEvidence.source_reference == technical_ref))
        if technical:
            technical.value_json = technical_data
        else:
            self.db.add(CuratorEvidence(candidate_id=candidate.id, evidence_type="TECHNICAL_SPEC", value_json=technical_data,
                source_kind=SOURCE_KIND, source_name="Catalog technical data", source_reference=technical_ref,
                confidence="HIGH", verification_status="VERIFIED")); added += 1
        self._remove_legacy_catalog_detail_evidence(candidate.id, catalog_id)
        return added

    def _remove_legacy_catalog_detail_evidence(self, candidate_id: str, catalog_id: str) -> None:
        """Consolidate pre-polish official attribute/image rows without data loss."""
        prefix = f"catalog:{catalog_id}:"
        legacy = self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id == candidate_id,
            CuratorEvidence.evidence_type.in_(("CATALOG_ATTRIBUTE", "CATALOG_PICTURE", "CATALOG_DATA")),
            CuratorEvidence.source_kind == SOURCE_KIND)).all()
        for evidence in legacy:
            if (evidence.source_reference or "").startswith(prefix):
                self.db.delete(evidence)

    def _exists(self, candidate_id: str, evidence_type: str, reference: str) -> bool:
        return self.db.scalar(select(CuratorEvidence.id).where(CuratorEvidence.candidate_id == candidate_id,
            CuratorEvidence.evidence_type == evidence_type, CuratorEvidence.source_reference == reference)) is not None
