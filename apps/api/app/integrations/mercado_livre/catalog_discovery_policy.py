from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


ALLOWED = "ALLOWED"
BLOCKED_POLICY = "BLOCKED_POLICY"
RESTRICTED_PRODUCT_CATEGORY = "RESTRICTED_PRODUCT_CATEGORY"


@dataclass(frozen=True)
class CatalogDiscoveryEligibility:
    status: str
    reason_code: str | None = None


def _normalize(query: str) -> str:
    decomposed = unicodedata.normalize("NFKD", query)
    ascii_query = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_query.casefold()).strip()


def catalog_discovery_eligibility(query: str) -> CatalogDiscoveryEligibility:
    """Apply the intentionally narrow policy gate before catalog discovery.

    This protects bulk discovery from creating commercial candidates for the
    objectively restricted product classes listed in the operator policy. It
    is lexical and deterministic by design; ambiguous categories remain allowed.
    """
    normalized = _normalize(query)
    restricted_patterns = (
        # Nicotine / electronic cigarettes.
        r"\b(vape|cigarro eletronico|e-cigarette|e cigarette|pod descartavel)\b",
        # Anabolics and injectable hormones, including common explicit product names.
        r"\b(anabolico|esteroide|masteron|hormonio injetavel|testosterona injetavel)\b",
        # Weapons and airsoft products. "Pistola" is intentionally contextual:
        # it also describes pressure-washer, paint, glue and silicone tools.
        r"\b(arma de fogo|rifle|revolver|espingarda|fuzil|municao|airsoft)\b",
        r"\bpistola\s*(?:9\s*mm|\.?(?:380|40|45)|glock|beretta|taurus)\b",
        # Adult sexual stimulation products.
        r"\b(vibrador|masturbador|sex toy|sugador clitoriano|estimulador sexual)\b",
    )
    if any(re.search(pattern, normalized) for pattern in restricted_patterns):
        return CatalogDiscoveryEligibility(BLOCKED_POLICY, RESTRICTED_PRODUCT_CATEGORY)
    return CatalogDiscoveryEligibility(ALLOWED)
