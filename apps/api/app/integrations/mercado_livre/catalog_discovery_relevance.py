from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# Generic product-complement vocabulary. It is used only to lower a result's
# rank when the operator did not explicitly search for that complement.
ACCESSORY_TERMS = frozenset({
    "adaptador", "conector", "niple", "suporte", "capa", "case", "refil", "tampa",
    "cabo", "carregador", "mangueira", "bico", "peca", "borrifador", "pulverizador",
})


@dataclass(frozen=True)
class DiscoveryRelevance:
    score: int
    reasons: tuple[str, ...]


def normalize_discovery_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", ascii_text.casefold())).strip()


def discovery_tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in normalize_discovery_text(text).split(" ") if token)


def catalog_discovery_relevance(query: str, title: str) -> DiscoveryRelevance:
    """Score title relevance for discovery only; this is not a product assessment."""
    query_text = normalize_discovery_text(query)
    query_tokens = discovery_tokens(query)
    title_tokens = discovery_tokens(title)
    if not query_tokens or not title_tokens:
        return DiscoveryRelevance(0, ())

    title_set = set(title_tokens)
    matched = [token for token in query_tokens if token in title_set]
    coverage = round(60 * len(matched) / len(query_tokens))
    score = coverage
    reasons: list[str] = ["TOKEN_COVERAGE"] if matched else []

    if query_text and query_text in normalize_discovery_text(title):
        score += 20
        reasons.append("PHRASE_MATCH")

    positions = [index for index, token in enumerate(title_tokens) if token in set(query_tokens)]
    if len(set(matched)) == len(set(query_tokens)) and positions:
        span = max(positions) - min(positions) + 1
        score += max(0, 10 - 2 * (span - len(query_tokens)))
        reasons.append("COMPACT_MATCH")
        if min(positions) == 0:
            score += 10
            reasons.append("TITLE_CENTERED")

    query_set = set(query_tokens)
    if any(term in title_set and term not in query_set for term in ACCESSORY_TERMS):
        score -= 30
        reasons.append("ACCESSORY_PENALTY")
    return DiscoveryRelevance(score, tuple(reasons))
