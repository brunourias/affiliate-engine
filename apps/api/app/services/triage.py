from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence, RadarRun, RadarSignal
from apps.api.app.services.operations import log_decision


GENERIC_QUERY_TERMS = frozenset({"produto", "produtos", "oferta", "ofertas", "ferramenta", "ferramentas", "todos", "todas"})
STOPWORDS = frozenset({"de", "da", "do", "das", "dos", "para", "em", "com", "e", "a", "o", "as", "os", "na", "no"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def query_tokens(query: str) -> set[str]:
    return {token for token in query.casefold().split() if token and token not in STOPWORDS}


class CandidateTriageService:
    """Ranks investigation priority from persisted, verifiable discovery data only."""

    def __init__(self, db: Session):
        self.db = db

    def triage_run(self, run_id: str) -> dict[str, Any]:
        run = self.db.get(RadarRun, run_id)
        if not run or run.provider != "MERCADO_LIVRE":
            raise ValueError("Execução do Radar não encontrada.")
        signals = list(self.db.scalars(select(RadarSignal).where(RadarSignal.radar_run_id == run.id, RadarSignal.entity_type == "QUERY")))
        by_signal = {signal.id: signal for signal in signals}
        linked = list(self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.evidence_type == "MARKET_SIGNAL", CuratorEvidence.source_reference.in_(by_signal) if by_signal else False)))
        candidate_ids = sorted({evidence.candidate_id for evidence in linked})
        candidates = list(self.db.scalars(select(CuratorCandidate).where(CuratorCandidate.id.in_(candidate_ids)))) if candidate_ids else []
        all_signal_evidence = list(self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id.in_(candidate_ids), CuratorEvidence.evidence_type == "MARKET_SIGNAL"))) if candidate_ids else []
        all_signal_ids = {e.source_reference for e in all_signal_evidence if e.source_reference}
        signal_rows = {signal.id: signal for signal in self.db.scalars(select(RadarSignal).where(RadarSignal.id.in_(all_signal_ids))).all()} if all_signal_ids else {}
        evidence_by_candidate: dict[str, list[CuratorEvidence]] = defaultdict(list)
        for evidence in self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id.in_(candidate_ids))).all() if candidate_ids else []:
            evidence_by_candidate[evidence.candidate_id].append(evidence)
        signals_by_candidate: dict[str, list[RadarSignal]] = defaultdict(list)
        for evidence in all_signal_evidence:
            signal = signal_rows.get(evidence.source_reference or "")
            if signal:
                signals_by_candidate[evidence.candidate_id].append(signal)
        domains_by_signal: dict[str, set[str]] = defaultdict(set)
        for candidate_id, candidate_evidence in evidence_by_candidate.items():
            technical = next((row for row in candidate_evidence if row.evidence_type == "TECHNICAL_SPEC" and isinstance(row.value_json, dict)), None)
            domain = technical.value_json.get("domainId") if technical else None
            if domain:
                for signal in signals_by_candidate[candidate_id]:
                    domains_by_signal[signal.id].add(str(domain))

        evaluated = []
        for candidate in candidates:
            score, reasons = self._score(candidate, evidence_by_candidate[candidate.id], signals_by_candidate[candidate.id], by_signal, domains_by_signal)
            candidate.triage_score = score
            candidate.triage_status = "TRIAGE_HIGH" if score >= 70 else "TRIAGE_MEDIUM" if score >= 45 else "TRIAGE_LOW"
            candidate.triage_reasons = reasons
            candidate.triage_evaluated_at = utcnow()
            evaluated.append(candidate)
        ranked = sorted(evaluated, key=lambda candidate: (-(candidate.triage_score or 0), candidate.id))
        limit = max(1, settings.curator_triage_enrichment_limit)
        marked_ids = {candidate.id for candidate in ranked[:limit]}
        for candidate in evaluated:
            candidate.triage_marked_for_enrichment = candidate.id in marked_ids
        log_decision(self.db, "SYSTEM", "RADAR_RUN", "CANDIDATE_TRIAGE_COMPLETED", run.id,
                     metadata={"runId": run.id, "candidatesEvaluated": len(evaluated), "markedForEnrichment": len(marked_ids), "enrichmentLimit": limit})
        self.db.commit()
        return {"runId": run.id, "candidatesEvaluated": len(evaluated), "enrichmentLimit": limit,
                "topCandidates": [self._public(candidate) for candidate in ranked[:limit]]}

    def _score(self, candidate: CuratorCandidate, evidence: list[CuratorEvidence], signals: list[RadarSignal], current_run_signals: dict[str, RadarSignal], domains_by_signal: dict[str, set[str]]) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        market = [row for row in evidence if row.evidence_type == "MARKET_SIGNAL"]
        relevance = max((int((row.value_json or {}).get("discoveryRelevanceScore") or 0) for row in market), default=0)
        relevance_contribution = round(max(0, min(100, relevance)) * 0.35)
        score += relevance_contribution
        if relevance >= 80: reasons.append("HIGH_DISCOVERY_RELEVANCE")
        elif relevance >= 50: reasons.append("MEDIUM_DISCOVERY_RELEVANCE")
        elif relevance: reasons.append("LOW_DISCOVERY_RELEVANCE")

        unique_signal_ids = {signal.id for signal in signals}
        unique_runs = {signal.radar_run_id for signal in signals}
        if len(unique_signal_ids) >= 2: score += min(10, len(unique_signal_ids) * 3); reasons.append("RECURRING_MARKET_SIGNAL")
        if len(unique_runs) >= 2: score += min(15, 5 * len(unique_runs)); reasons.append("RECURRING_RADAR_RUNS")
        best_rank = min((signal.rank for signal in signals if signal.rank is not None), default=None)
        if best_rank is not None and best_rank <= 3: score += 8; reasons.append("HIGH_RADAR_RANK")
        elif best_rank is not None and best_rank <= 10: score += 4; reasons.append("RADAR_RANK")
        if any(signal.source_type == "TREND_CATEGORY" for signal in signals): score += 8; reasons.append("CATEGORY_TREND_SIGNAL")

        identity = next((row for row in evidence if row.evidence_type == "IDENTITY"), None)
        technical = next((row for row in evidence if row.evidence_type == "TECHNICAL_SPEC"), None)
        technical_data = technical.value_json if technical and isinstance(technical.value_json, dict) else {}
        if identity and identity.value_text: score += 5; reasons.append("CATALOG_IDENTITY_AVAILABLE")
        if technical_data.get("officialCatalogData", {}).get("status") == "active": score += 5; reasons.append("CATALOG_ACTIVE")
        if technical_data.get("domainId"): score += 5; reasons.append("CATALOG_DOMAIN_IDENTIFIED")
        if technical_data.get("attributes"): score += 7; reasons.append("CATALOG_ATTRIBUTES_AVAILABLE")
        if technical_data.get("pictures"): score += 5; reasons.append("OFFICIAL_IMAGES_AVAILABLE")

        linked_current = [signal for signal in signals if signal.id in current_run_signals]
        queries = [str((row.value_json or {}).get("query") or "") for row in market if row.source_reference in current_run_signals]
        queries = [query for query in queries if query] or [signal.display_text or "" for signal in linked_current] or [signal.display_text or "" for signal in signals]
        if any(self._generic_query(query) for query in queries): score -= 12; reasons.append("GENERIC_QUERY")
        elif any(len(query_tokens(query)) >= 2 for query in queries): score += 5; reasons.append("SPECIFIC_QUERY")
        if self._ambiguous(signals, domains_by_signal): score -= 10; reasons.append("AMBIGUOUS_QUERY")
        return max(0, min(100, score)), list(dict.fromkeys(reasons))

    @staticmethod
    def _generic_query(query: str) -> bool:
        tokens = query_tokens(query)
        return bool(tokens) and (len(tokens) <= 1 or tokens.issubset(GENERIC_QUERY_TERMS))

    @staticmethod
    def _ambiguous(signals: list[RadarSignal], domains_by_signal: dict[str, set[str]]) -> bool:
        return any(len(domains_by_signal.get(signal.id, set())) >= 3 and len(query_tokens(signal.display_text or "")) <= 1 for signal in signals)

    @staticmethod
    def _public(candidate: CuratorCandidate) -> dict[str, Any]:
        return {"candidateId": candidate.id, "title": candidate.working_title or candidate.external_id,
                "triageScore": candidate.triage_score, "triageStatus": candidate.triage_status,
                "reasons": candidate.triage_reasons, "markedForEnrichment": candidate.triage_marked_for_enrichment}
