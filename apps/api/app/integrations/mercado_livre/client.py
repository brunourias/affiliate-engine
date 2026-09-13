import time
from typing import Any

import httpx

from .models import CapabilityResult

BASE_URL = "https://api.mercadolibre.com"


class MercadoLivreClient:
    def __init__(self, access_token: str = "", transport: httpx.BaseTransport | None = None, timeout: float = 8.0):
        self.access_token = access_token.strip()
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "AffiliateEngine/0.2 capability-diagnostics"},
        )

    def close(self) -> None:
        self._client.close()

    def get(self, key: str, endpoint: str, *, requires_auth: bool = False, params: dict[str, Any] | None = None) -> CapabilityResult:
        if requires_auth and not self.access_token:
            return CapabilityResult(key, "NOT_CONFIGURED", endpoint, reason_code="TOKEN_NOT_CONFIGURED", message="Token de acesso não configurado.")
        headers = {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
        started = time.perf_counter()
        try:
            response = self._client.get(endpoint, params=params, headers=headers)
            latency = round((time.perf_counter() - started) * 1000)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            reason = "TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "NETWORK_ERROR"
            return CapabilityResult(key, "DEGRADED", endpoint, latency_ms=round((time.perf_counter() - started) * 1000), reason_code=reason, message="O Mercado Livre não respondeu dentro das condições esperadas.")
        status = response.status_code
        mapped = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 429: "DEGRADED"}.get(status)
        if mapped:
            metadata = {}
            retry_after = response.headers.get("Retry-After")
            if status == 429 and retry_after:
                metadata["retryAfter"] = retry_after[:40]
            return CapabilityResult(key, mapped, endpoint, status, latency, f"HTTP_{status}", self._message(status), metadata)
        if status == 404:
            return CapabilityResult(key, "NOT_SUPPORTED", endpoint, status, latency, "HTTP_404", "Recurso não encontrado ou indisponível para este contexto.")
        if status >= 500:
            return CapabilityResult(key, "DEGRADED", endpoint, status, latency, "PROVIDER_ERROR", "O serviço oficial do Mercado Livre está temporariamente indisponível.")
        if status < 200 or status >= 300:
            return CapabilityResult(key, "DEGRADED", endpoint, status, latency, f"HTTP_{status}", "O endpoint oficial recusou a solicitação.")
        try:
            data = response.json()
        except ValueError:
            return CapabilityResult(key, "DEGRADED", endpoint, status, latency, "INVALID_JSON", "O endpoint retornou uma resposta inválida.")
        return CapabilityResult(key, "AVAILABLE", endpoint, status, latency, "HTTP_200", "Capacidade oficial disponível.", data=data)

    @staticmethod
    def _message(status: int) -> str:
        return {
            401: "Credencial ausente, inválida ou expirada.",
            403: "O acesso a esta capacidade não foi autorizado.",
            429: "Limite de requisições atingido; tente novamente mais tarde.",
        }[status]
