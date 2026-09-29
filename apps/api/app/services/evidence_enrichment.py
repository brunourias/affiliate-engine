from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence, RadarRun, RadarSignal
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.integrations.mercado_livre.models import CapabilityResult
from apps.api.app.integrations.mercado_livre.oauth import MercadoLivreTokenManager
from apps.api.app.services.curator import refresh
from apps.api.app.services.operations import log_decision


SOURCE_KEYS = ("catalog", "buyBox", "price", "reviews", "sellerReputation")
STATUSES = ("AVAILABLE", "UNAVAILABLE", "FORBIDDEN", "FAILED")


def now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


class CandidateEvidenceEnrichmentService:
    def __init__(self, db: Session, client: MercadoLivreClient | None = None):
        self.db = db
        self.client = client or MercadoLivreClient(token_manager=MercadoLivreTokenManager(db))
        self.owns = client is None

    def close(self) -> None:
        if self.owns:
            self.client.close()

    @staticmethod
    def _status(result: CapabilityResult) -> dict:
        status = "AVAILABLE" if result.status == "AVAILABLE" else "UNAVAILABLE" if result.http_status == 404 else "FORBIDDEN" if result.status == "FORBIDDEN" or result.http_status == 403 else "FAILED"
        output = {"status": status}
        if result.reason_code:
            output["reasonCode"] = result.reason_code
        if result.http_status:
            output["httpStatus"] = result.http_status
        return output

    def enrich_run(self, run_id: str) -> dict:
        if not self.db.get(RadarRun, run_id):
            raise ValueError("Execução do Radar não encontrada.")
        signal_ids = set(self.db.scalars(select(RadarSignal.id).where(RadarSignal.radar_run_id == run_id)))
        linked = set(self.db.scalars(select(CuratorEvidence.candidate_id).where(
            CuratorEvidence.evidence_type == "MARKET_SIGNAL",
            CuratorEvidence.source_reference.in_(signal_ids) if signal_ids else False,
        )))
        candidates = list(self.db.scalars(select(CuratorCandidate).where(
            CuratorCandidate.id.in_(linked), CuratorCandidate.triage_marked_for_enrichment.is_(True),
        ).order_by(CuratorCandidate.triage_score.desc(), CuratorCandidate.id).limit(max(1, settings.curator_triage_enrichment_limit))))
        result = {"runId": run_id, "candidatesRequested": len(candidates), "candidatesProcessed": 0,
                  "candidatesEnriched": 0, "catalogAvailableCount": 0, "commercialEvidenceAvailableCount": 0,
                  "candidatesWithoutBuyBox": 0, "evidenceAdded": 0, "evidenceChanged": 0,
                  "evidenceUnchanged": 0, "priceAvailableCount": 0, "reviewsAvailableCount": 0,
                  "sellerReputationAvailableCount": 0,
                  "sourceSummary": {key: {status: 0 for status in STATUSES} for key in SOURCE_KEYS}, "candidates": []}
        log_decision(self.db, "SYSTEM", "RADAR_RUN", "EVIDENCE_ENRICHMENT_STARTED", run_id,
                     metadata={"runId": run_id, "candidatesRequested": len(candidates)})
        for candidate in candidates:
            summary = self.enrich_candidate(candidate.id, commit=False, run_id=run_id)
            result["candidatesProcessed"] += 1
            result["candidates"].append(summary)
            result["candidatesEnriched"] += summary["sourceStatuses"]["catalog"]["status"] == "AVAILABLE"
            result["catalogAvailableCount"] += summary["sourceStatuses"]["catalog"]["status"] == "AVAILABLE"
            result["commercialEvidenceAvailableCount"] += summary["commercialEvidenceAvailable"]
            result["candidatesWithoutBuyBox"] += summary["sourceStatuses"]["buyBox"]["status"] == "UNAVAILABLE"
            for key, value in summary["sourceStatuses"].items():
                result["sourceSummary"][key][value["status"]] += 1
            for key in ("evidenceAdded", "evidenceChanged", "evidenceUnchanged"):
                result[key] += summary[key]
            result["priceAvailableCount"] += summary["sourceStatuses"]["price"]["status"] == "AVAILABLE"
            result["reviewsAvailableCount"] += summary["sourceStatuses"]["reviews"]["status"] == "AVAILABLE"
            result["sellerReputationAvailableCount"] += summary["sourceStatuses"]["sellerReputation"]["status"] == "AVAILABLE"
        log_decision(self.db, "SYSTEM", "RADAR_RUN", "EVIDENCE_ENRICHMENT_COMPLETED", run_id,
                     metadata={key: result[key] for key in ("runId", "candidatesProcessed", "evidenceAdded", "evidenceChanged", "evidenceUnchanged")})
        self.db.commit()
        return result

    def enrich_candidate(self, candidate_id: str, *, commit: bool = True, run_id: str | None = None) -> dict:
        """Run the same official-source enrichment core for one candidate.

        This deliberately does not create a RadarRun: an explicit commercial
        binding is useful for manual candidates as well as for batch discovery.
        """
        candidate = self.db.get(CuratorCandidate, candidate_id)
        if not candidate:
            raise ValueError("Candidato não encontrado.")
        summary = self._candidate(candidate)
        refresh(self.db, candidate)
        log_decision(self.db, "SYSTEM", "CURATOR_CANDIDATE", "CANDIDATE_ENRICHED", candidate.id,
                     metadata={"runId": run_id, "candidateId": candidate.id,
                               "catalogProductId": summary["catalogProductId"], "observedItemId": summary["observedItemId"],
                               "sourceStatuses": {key: value["status"] for key, value in summary["sourceStatuses"].items()},
                               "counts": {key: summary[key] for key in ("evidenceAdded", "evidenceChanged", "evidenceUnchanged")}})
        if commit:
            self.db.commit()
        return summary

    def _candidate(self, candidate: CuratorCandidate) -> dict:
        statuses = {key: {"status": "UNAVAILABLE"} for key in SOURCE_KEYS}
        binding_row = self.db.scalar(select(CuratorEvidence).where(
            CuratorEvidence.candidate_id == candidate.id,
            CuratorEvidence.evidence_type == "MARKETPLACE_LISTING_BINDING",
        ).order_by(CuratorEvidence.observed_at.desc()))
        binding = dict(binding_row.value_json or {}) if binding_row else {}
        catalog_id = binding.get("catalogProductId") or (candidate.external_id if candidate.entity_type == "PRODUCT" else None)
        explicit_item_id = binding.get("sourceItemId") or binding.get("itemId")
        output = {"candidateId": candidate.id, "catalogProductId": catalog_id, "observedItemId": None,
                  "observedSellerId": None, "sourceStatuses": statuses, "commercialEvidenceAvailable": False,
                  "evidenceAdded": 0, "evidenceChanged": 0, "evidenceUnchanged": 0}

        catalog = None
        if catalog_id:
            catalog_result = self.client.get("CATALOG_PRODUCT", f"/products/{catalog_id}", requires_auth=True)
            statuses["catalog"] = self._status(catalog_result)
            catalog = catalog_result.data if catalog_result.status == "AVAILABLE" and isinstance(catalog_result.data, dict) else None
        if catalog is None and not explicit_item_id:
            return output

        box = catalog.get("buy_box_winner") if catalog else None
        box_item_id = None
        box_seller_id = None
        if isinstance(box, dict):
            statuses["buyBox"] = {"status": "AVAILABLE"}
            box_item_id = str(box.get("item_id") or "") or None
            box_seller_id = str(box.get("seller_id") or "") or None
        # buy_box_winner is optional; explicit operator binding has priority and absence never fails triage/ranking.
        item_id = explicit_item_id or box_item_id
        seller_id = box_seller_id
        if not explicit_item_id and isinstance(box, dict) and isinstance(box.get("price"), (int, float)) and not isinstance(box.get("price"), bool):
            self._record(output, candidate, "CURRENT_PRICE", {"catalogProductId": catalog_id, "observedItemId": item_id,
                         "currency": box.get("currency_id"), "amount": box["price"]})
            statuses["price"] = {"status": "AVAILABLE"}
        if not item_id:
            return output

        output["observedItemId"] = item_id
        # An operator-selected offer must be validated as an item.  Buy-box data
        # already came from the official catalog response and remains optional.
        if explicit_item_id:
            item_result = self.client.get("ITEM_DETAILS", f"/items/{item_id}", requires_auth=True)
            if item_result.status != "AVAILABLE" or not isinstance(item_result.data, dict):
                failure = self._status(item_result)
                if statuses["price"]["status"] != "AVAILABLE":
                    statuses["price"] = failure
                statuses["reviews"] = failure
                statuses["sellerReputation"] = failure
                return output
            item = item_result.data
            seller_id = str(item.get("seller_id") or seller_id or "") or None
            if statuses["price"]["status"] != "AVAILABLE" and isinstance(item.get("price"), (int, float)) and not isinstance(item.get("price"), bool):
                self._record(output, candidate, "CURRENT_PRICE", {"catalogProductId": catalog_id, "observedItemId": item_id,
                             "sourceItemId": item_id, "commercialSource": "EXPLICIT_BINDING",
                             "currency": item.get("currency_id"), "amount": item["price"]})
                statuses["price"] = {"status": "AVAILABLE"}
        output["observedSellerId"] = seller_id
        if statuses["price"]["status"] != "AVAILABLE":
            prices = self.client.get("ITEM_PRICES", f"/items/{item_id}/prices", requires_auth=True)
            statuses["price"] = self._status(prices)
        reviews = self.client.get("ITEM_REVIEWS", f"/reviews/item/{item_id}", requires_auth=True,
                                  params={"catalog_product_id": catalog_id} if catalog_id else None)
        statuses["reviews"] = self._status(reviews)
        if reviews.status == "AVAILABLE" and isinstance(reviews.data, dict):
            data = reviews.data
            paging = data.get("paging") if isinstance(data.get("paging"), dict) else {}
            sample = data.get("reviews") if isinstance(data.get("reviews"), list) else []
            self._record(output, candidate, "REVIEW_SUMMARY", {"catalogProductId": catalog_id, "itemId": item_id,
                         "sourceItemId": item_id, "commercialSource": "EXPLICIT_BINDING" if explicit_item_id else "BUY_BOX",
                         "ratingAverage": data.get("rating_average"), "totalReviews": paging.get("total"),
                         "reviewsWithComment": data.get("reviews_with_comment"), "ratingLevels": data.get("rating_levels"),
                         "sampleCount": min(len(sample), 20), "reviewIds": [entry.get("id") for entry in sample[:20] if isinstance(entry, dict) and entry.get("id") is not None]})
        if seller_id:
            seller = self.client.get("SELLER_REPUTATION", f"/users/{seller_id}", requires_auth=True)
            statuses["sellerReputation"] = self._status(seller)
            if seller.status == "AVAILABLE" and isinstance(seller.data, dict) and isinstance(seller.data.get("seller_reputation"), dict):
                self._record(output, candidate, "SELLER_REPUTATION", {"sellerId": seller_id, "sourceItemId": item_id,
                             "commercialSource": "EXPLICIT_BINDING" if explicit_item_id else "BUY_BOX",
                             "sellerReputation": seller.data["seller_reputation"]})
        return output

    def _record(self, output: dict, candidate: CuratorCandidate, kind: str, value: dict) -> None:
        provenance = {
            key: value[key]
            for key in ("sourceItemId", "commercialSource")
            if value.get(key) is not None
        }
        output["evidence" + self._temporal(candidate, kind, value, provenance=provenance)] += 1
        output["commercialEvidenceAvailable"] = True

    def _temporal(self, candidate: CuratorCandidate, kind: str, value: dict, *, provenance: dict | None = None) -> str:
        active = self.db.scalar(select(CuratorEvidence).where(
            CuratorEvidence.candidate_id == candidate.id, CuratorEvidence.evidence_type == kind,
            CuratorEvidence.valid_until.is_(None),
        ).order_by(CuratorEvidence.observed_at.desc()))
        digest = fingerprint(value)
        if active and (active.metadata_ or {}).get("fingerprint") == digest:
            active.observed_at = now()
            return "Unchanged"
        action = "Changed" if active else "Added"
        if active:
            active.valid_until = now()
        self.db.add(CuratorEvidence(candidate_id=candidate.id, evidence_type=kind, value_json=value,
                    value_cents=round(value["amount"] * 100) if kind == "CURRENT_PRICE" else None,
                    source_kind="MERCADO_LIVRE_OFFICIAL_API", source_name="Mercado Livre official API",
                    source_reference=f"enrichment:{kind}:{digest}", confidence="HIGH", verification_status="VERIFIED",
                    observed_at=now(), metadata_={"fingerprint": digest, **(provenance or {})}))
        return action
