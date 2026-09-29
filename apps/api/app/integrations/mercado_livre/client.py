import re
import time
from typing import Any

import httpx

from .models import CapabilityResult
from .oauth import MercadoLivreAuthError, MercadoLivreTokenManager

BASE_URL = "https://api.mercadolibre.com"
SAFE_REMOTE_VALUE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
POLICY_AUTH_ERROR = "PA_UNAUTHORIZED_RESULT_FROM_POLICIES"


def _safe_remote_value(value: Any) -> str | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and SAFE_REMOTE_VALUE.fullmatch(value):
        return value
    return None


def safe_remote_error_metadata(response: httpx.Response) -> dict[str, str | int]:
    """Extract only allowlisted scalar error identifiers; never retain the body/message."""
    try:
        payload = response.json()
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    error = payload.get("error")
    error_object = error if isinstance(error, dict) else {}
    cause = error_object.get("cause", payload.get("cause"))
    if isinstance(cause, list):
        cause = next((entry for entry in cause if isinstance(entry, dict)), {})
    if not isinstance(cause, dict):
        cause = {}
    candidates = {
        "remoteStatus": error_object.get("status", payload.get("status")),
        "remoteErrorCode": error_object.get("code", payload.get("code")),
        "remoteErrorType": error_object.get("type", error if isinstance(error, str) else payload.get("type")),
        "remoteCauseCode": cause.get("code"),
        "remoteCauseType": cause.get("type"),
    }
    return {key: safe for key, value in candidates.items() if (safe := _safe_remote_value(value)) is not None}


class MercadoLivreClient:
    def __init__(self, access_token: str = "", transport: httpx.BaseTransport | None = None, timeout: float = 8.0,
                 token_manager: MercadoLivreTokenManager | None = None):
        self.access_token = access_token.strip()
        self.token_manager = token_manager
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "AffiliateEngine/0.2 capability-diagnostics"},
        )

    def close(self) -> None:
        self._client.close()
        if self.token_manager:
            self.token_manager.close()

    def get(self, key: str, endpoint: str, *, requires_auth: bool = False, params: dict[str, Any] | None = None) -> CapabilityResult:
        try:
            token = self.token_manager.access_token() if requires_auth and self.token_manager else self.access_token
        except MercadoLivreAuthError as exc:
            status = "DEGRADED" if exc.temporary else "NOT_CONFIGURED" if exc.code in {"TOKEN_NOT_CONFIGURED", "TOKEN_ENCRYPTION_KEY_NOT_CONFIGURED"} else "UNAUTHORIZED"
            return CapabilityResult(key, status, endpoint, reason_code=exc.code, message=exc.public_message)
        if requires_auth and not token:
            return CapabilityResult(key, "NOT_CONFIGURED", endpoint, reason_code="TOKEN_NOT_CONFIGURED", message="Token de acesso não configurado.")
        # Public capabilities must not inherit an unrelated/stale credential.
        # Authenticated capabilities opt in explicitly through requires_auth.
        headers = {"Authorization": f"Bearer {token}"} if requires_auth and token else {}
        started = time.perf_counter()
        try:
            response = self._client.get(endpoint, params=params, headers=headers)
            should_refresh = response.status_code == 401
            if response.status_code == 403 and requires_auth and self.token_manager:
                metadata = safe_remote_error_metadata(response)
                if metadata.get("remoteErrorCode") == POLICY_AUTH_ERROR:
                    probe = self._auth_probe(token)
                    if isinstance(probe, CapabilityResult):
                        return CapabilityResult(key, probe.status, endpoint, probe.http_status,
                                                round((time.perf_counter() - started) * 1000), probe.reason_code,
                                                probe.message, probe.metadata)
                    should_refresh = probe
            if should_refresh and requires_auth and self.token_manager:
                try:
                    token = self.token_manager.refresh_after_unauthorized(token)
                except MercadoLivreAuthError as exc:
                    status = "DEGRADED" if exc.temporary else "UNAUTHORIZED"
                    return CapabilityResult(key, status, endpoint, response.status_code,
                                            round((time.perf_counter() - started) * 1000), exc.code, exc.public_message)
                response = self._client.get(endpoint, params=params, headers={"Authorization": f"Bearer {token}"})
                retry_metadata = safe_remote_error_metadata(response) if response.status_code == 403 else {}
                if response.status_code == 401 or (response.status_code == 403 and retry_metadata.get("remoteErrorCode") == POLICY_AUTH_ERROR):
                    self.token_manager.mark_reauth_required("AUTHENTICATION_REJECTED_AFTER_REFRESH", response.status_code)
            latency = round((time.perf_counter() - started) * 1000)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            reason = "TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "NETWORK_ERROR"
            return CapabilityResult(key, "DEGRADED", endpoint, latency_ms=round((time.perf_counter() - started) * 1000), reason_code=reason, message="O Mercado Livre não respondeu dentro das condições esperadas.")
        status = response.status_code
        mapped = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 429: "DEGRADED"}.get(status)
        if mapped:
            metadata = safe_remote_error_metadata(response)
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

    def _auth_probe(self, token: str) -> bool | CapabilityResult:
        """Validate the same token once, bypassing normal retry logic to prevent recursion."""
        try:
            response = self._client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            reason = "AUTH_PROBE_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "AUTH_PROBE_NETWORK_ERROR"
            return CapabilityResult("AUTH_PROBE", "DEGRADED", "/users/me", reason_code=reason,
                                    message="Não foi possível validar temporariamente a conexão com o Mercado Livre.")
        if response.status_code == 200:
            return False
        metadata = safe_remote_error_metadata(response)
        if response.status_code == 401:
            return True
        if response.status_code == 403 and metadata.get("remoteErrorCode") == POLICY_AUTH_ERROR:
            return True
        if response.status_code == 429 or response.status_code >= 500:
            return CapabilityResult("AUTH_PROBE", "DEGRADED", "/users/me", response.status_code,
                                    reason_code=f"AUTH_PROBE_HTTP_{response.status_code}",
                                    message="Não foi possível validar temporariamente a conexão com o Mercado Livre.",
                                    metadata=metadata)
        # An inconclusive probe must never consume the rotating refresh token.
        return False

    @staticmethod
    def _message(status: int) -> str:
        return {
            401: "Credencial ausente, inválida ou expirada.",
            403: "O acesso a esta capacidade não foi autorizado.",
            429: "Limite de requisições atingido; tente novamente mais tarde.",
        }[status]
