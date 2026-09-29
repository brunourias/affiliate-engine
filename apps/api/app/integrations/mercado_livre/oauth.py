from __future__ import annotations

import base64
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import DecisionLog, MarketplaceConnection, MarketplaceOAuthCredential

PROVIDER = "MERCADO_LIVRE"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
_REFRESH_LOCK = threading.Lock()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class MercadoLivreAuthError(RuntimeError):
    def __init__(self, code: str, message: str, *, temporary: bool = False):
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.temporary = temporary


class TokenCipher:
    """AES-256-GCM envelope; the database contains nonce+ciphertext only."""

    def __init__(self, encoded_key: str):
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
        except Exception as exc:
            raise MercadoLivreAuthError("TOKEN_ENCRYPTION_KEY_INVALID", "Chave de proteção OAuth inválida.") from exc
        if len(key) != 32:
            raise MercadoLivreAuthError("TOKEN_ENCRYPTION_KEY_INVALID", "Chave de proteção OAuth inválida.")
        self._cipher = AESGCM(key)

    def encrypt(self, value: str) -> str:
        nonce = os.urandom(12)
        sealed = self._cipher.encrypt(nonce, value.encode("utf-8"), PROVIDER.encode("ascii"))
        return base64.urlsafe_b64encode(nonce + sealed).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(value.encode("ascii"))
            return self._cipher.decrypt(raw[:12], raw[12:], PROVIDER.encode("ascii")).decode("utf-8")
        except Exception as exc:
            raise MercadoLivreAuthError("TOKEN_DECRYPTION_FAILED", "Não foi possível acessar a credencial OAuth gerenciada.") from exc


@dataclass(frozen=True)
class TokenSnapshot:
    access_token: str
    refresh_token: str
    expires_at: datetime | None
    version: int
    managed: bool


class MercadoLivreTokenManager:
    def __init__(self, db: Session, *, transport: httpx.BaseTransport | None = None, now=utcnow):
        self.db = db
        self._now = now
        self._client = httpx.Client(timeout=settings.meli_oauth_timeout_seconds, transport=transport)

    def close(self) -> None:
        self._client.close()

    @property
    def auth_mode(self) -> str:
        return "OAUTH_MANAGED" if self._credential() is not None else "ENV_ACCESS_TOKEN" if settings.meli_access_token else "ANONYMOUS"

    def public_status(self) -> dict[str, Any]:
        row = self._credential()
        status = row.credential_status if row else "BOOTSTRAP" if settings.meli_access_token else "NOT_CONFIGURED"
        return {
            "provider": PROVIDER,
            "authMode": self.auth_mode,
            "status": status,
            "externalAccountId": row.external_account_id if row else None,
            "expiresAt": _aware(row.expires_at) if row else None,
            "lastRefreshAt": _aware(row.last_refresh_at) if row else None,
            "reauthRequired": status == "REAUTH_REQUIRED",
        }

    def access_token(self) -> str:
        snapshot = self._snapshot()
        if not snapshot.access_token:
            raise MercadoLivreAuthError("TOKEN_NOT_CONFIGURED", "Token de acesso não configurado.")
        if snapshot.managed and snapshot.expires_at and snapshot.expires_at <= self._now() + timedelta(seconds=settings.meli_token_refresh_margin_seconds):
            return self.refresh(snapshot).access_token
        return snapshot.access_token

    def refresh_after_unauthorized(self, failed_access_token: str) -> str:
        return self.refresh(self._snapshot(), failed_access_token=failed_access_token).access_token

    def mark_reauth_required(self, reason: str, http_status: int | None = None) -> None:
        self._mark("REAUTH_REQUIRED", "MELI_REAUTH_REQUIRED", reason, http_status)

    def refresh(self, observed: TokenSnapshot | None = None, *, failed_access_token: str | None = None) -> TokenSnapshot:
        observed = observed or self._snapshot()
        with _REFRESH_LOCK:
            self.db.expire_all()
            refreshing = self._credential()
            if refreshing and refreshing.credential_status == "REFRESHING":
                stale_before = self._now() - timedelta(seconds=settings.meli_oauth_timeout_seconds + 30)
                if _aware(refreshing.updated_at) and _aware(refreshing.updated_at) <= stale_before:
                    refreshing.credential_status = "DEGRADED"
                    refreshing.refresh_not_before = None
                    self.db.commit(); self.db.expire_all()
            current = self._snapshot()
            # Another request already rotated the credential while this request waited.
            current_row = self._credential()
            if current.managed and current.version != observed.version and current_row.credential_status != "REFRESHING":
                return current
            if current_row and current_row.credential_status == "REFRESHING":
                raise MercadoLivreAuthError("TOKEN_REFRESH_IN_PROGRESS", "A credencial OAuth já está sendo renovada.", temporary=True)
            if failed_access_token and current.access_token != failed_access_token:
                return current
            row = self._credential()
            if row and _aware(row.refresh_not_before) and _aware(row.refresh_not_before) > self._now():
                raise MercadoLivreAuthError("TOKEN_REFRESH_DEGRADED", "A renovação da conexão está temporariamente indisponível.", temporary=True)
            if not current.refresh_token:
                self._mark("REAUTH_REQUIRED", "MELI_REAUTH_REQUIRED", "REFRESH_TOKEN_NOT_CONFIGURED")
                raise MercadoLivreAuthError("REAUTH_REQUIRED", "A conexão com o Mercado Livre precisa ser renovada.")
            if not settings.meli_client_id or not settings.meli_client_secret:
                self._mark("CONFIGURATION_ERROR", "MELI_TOKEN_REFRESH_FAILED", "INVALID_CLIENT_CONFIGURATION")
                raise MercadoLivreAuthError("INVALID_CLIENT_CONFIGURATION", "Configuração OAuth do Mercado Livre incompleta.")
            if current.managed:
                row = self._credential()
                claimed = self.db.execute(update(MarketplaceOAuthCredential).where(
                    MarketplaceOAuthCredential.id == row.id,
                    MarketplaceOAuthCredential.version == current.version,
                    MarketplaceOAuthCredential.credential_status.in_(["AVAILABLE", "DEGRADED"]),
                ).values(credential_status="REFRESHING", version=current.version + 1, updated_at=self._now()))
                if claimed.rowcount != 1:
                    self.db.rollback(); self.db.expire_all()
                    latest = self._snapshot()
                    if latest.version != current.version and self._credential().credential_status != "REFRESHING":
                        return latest
                    raise MercadoLivreAuthError("TOKEN_REFRESH_IN_PROGRESS", "A credencial OAuth já está sendo renovada.", temporary=True)
                self.db.commit()
                current = TokenSnapshot(current.access_token, current.refresh_token, current.expires_at, current.version + 1, True)
            return self._remote_refresh(current)

    def _remote_refresh(self, current: TokenSnapshot) -> TokenSnapshot:
        try:
            response = self._client.post(TOKEN_URL, data={
                "grant_type": "refresh_token",
                "client_id": settings.meli_client_id,
                "client_secret": settings.meli_client_secret,
                "refresh_token": current.refresh_token,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            self._mark("DEGRADED", "MELI_TOKEN_REFRESH_FAILED", "NETWORK_ERROR", retry_after_seconds=60)
            raise MercadoLivreAuthError("TOKEN_REFRESH_DEGRADED", "Não foi possível renovar a conexão com o Mercado Livre.", temporary=True) from exc
        payload = self._safe_json(response)
        if response.status_code < 200 or response.status_code >= 300:
            remote_code = payload.get("error") if isinstance(payload.get("error"), str) else f"HTTP_{response.status_code}"
            if remote_code == "invalid_grant":
                self._mark("REAUTH_REQUIRED", "MELI_REAUTH_REQUIRED", remote_code, response.status_code)
                raise MercadoLivreAuthError("REAUTH_REQUIRED", "A conexão com o Mercado Livre precisa ser renovada.")
            if remote_code == "invalid_client":
                self._mark("CONFIGURATION_ERROR", "MELI_TOKEN_REFRESH_FAILED", remote_code, response.status_code)
                raise MercadoLivreAuthError("INVALID_CLIENT_CONFIGURATION", "Configuração OAuth do Mercado Livre inválida.")
            temporary = response.status_code == 429 or response.status_code >= 500
            status = "DEGRADED" if temporary else "REAUTH_REQUIRED"
            retry_after = self._retry_after_seconds(response) if response.status_code == 429 else 60 if response.status_code >= 500 else None
            self._mark(status, "MELI_TOKEN_REFRESH_FAILED", remote_code, response.status_code, retry_after_seconds=retry_after)
            raise MercadoLivreAuthError("TOKEN_REFRESH_DEGRADED" if temporary else "REAUTH_REQUIRED",
                                         "Não foi possível renovar a conexão com o Mercado Livre.", temporary=temporary)
        access = payload.get("access_token")
        refresh = payload.get("refresh_token")
        expires_in = payload.get("expires_in")
        if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh or not isinstance(expires_in, int) or expires_in <= 0:
            self._mark("DEGRADED", "MELI_TOKEN_REFRESH_FAILED", "INVALID_TOKEN_RESPONSE", response.status_code)
            raise MercadoLivreAuthError("INVALID_TOKEN_RESPONSE", "O Mercado Livre retornou uma credencial inválida.", temporary=True)
        cipher = self._cipher()
        now = self._now()
        row = self._credential()
        if row is None:
            row = MarketplaceOAuthCredential(provider=PROVIDER, encrypted_access_token="", encrypted_refresh_token="")
            self.db.add(row)
        row.encrypted_access_token = cipher.encrypt(access)
        row.encrypted_refresh_token = cipher.encrypt(refresh)
        row.expires_at = now + timedelta(seconds=expires_in)
        row.last_refresh_at = now
        row.external_account_id = str(payload["user_id"]) if payload.get("user_id") is not None else row.external_account_id
        row.token_type = str(payload.get("token_type"))[:32] if payload.get("token_type") else None
        row.scope = str(payload.get("scope")) if payload.get("scope") else None
        row.credential_status = "AVAILABLE"
        row.refresh_not_before = None
        row.version = (row.version or 0) + 1
        row.updated_at = now
        self._sync_connection(row)
        self._decision("MELI_TOKEN_REFRESH_SUCCEEDED", "AVAILABLE", "HTTP_200", response.status_code, row.expires_at)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise MercadoLivreAuthError("TOKEN_PERSISTENCE_FAILED", "Não foi possível persistir a credencial OAuth renovada.")
        return TokenSnapshot(access, refresh, _aware(row.expires_at), row.version, True)

    def _credential(self) -> MarketplaceOAuthCredential | None:
        return self.db.scalar(select(MarketplaceOAuthCredential).where(MarketplaceOAuthCredential.provider == PROVIDER))

    def _snapshot(self) -> TokenSnapshot:
        row = self._credential()
        if row:
            if row.credential_status in {"REAUTH_REQUIRED", "CONFIGURATION_ERROR"}:
                raise MercadoLivreAuthError(row.credential_status, "A conexão com o Mercado Livre precisa ser renovada." if row.credential_status == "REAUTH_REQUIRED" else "Configuração OAuth do Mercado Livre inválida.")
            cipher = self._cipher()
            return TokenSnapshot(cipher.decrypt(row.encrypted_access_token), cipher.decrypt(row.encrypted_refresh_token), _aware(row.expires_at), row.version, True)
        return TokenSnapshot(settings.meli_access_token.strip(), settings.meli_refresh_token.strip(), None, 0, False)

    def _cipher(self) -> TokenCipher:
        if not settings.meli_token_encryption_key:
            raise MercadoLivreAuthError("TOKEN_ENCRYPTION_KEY_NOT_CONFIGURED", "Chave de proteção OAuth não configurada.")
        return TokenCipher(settings.meli_token_encryption_key)

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except ValueError:
            return {}

    def _sync_connection(self, credential: MarketplaceOAuthCredential) -> None:
        connection = self.db.scalar(select(MarketplaceConnection).where(MarketplaceConnection.provider == PROVIDER))
        if connection:
            connection.auth_mode = "OAUTH_MANAGED"
            connection.external_account_id = credential.external_account_id or connection.external_account_id
            metadata = dict(connection.metadata_ or {})
            metadata.update({"authStatus": credential.credential_status, "reauthRequired": credential.credential_status == "REAUTH_REQUIRED",
                             "expiresAt": credential.expires_at.isoformat() if credential.expires_at else None,
                             "lastRefreshAt": credential.last_refresh_at.isoformat() if credential.last_refresh_at else None})
            connection.metadata_ = metadata

    def _mark(self, status: str, action: str, reason: str, http_status: int | None = None,
              retry_after_seconds: int | None = None) -> None:
        row = self._credential()
        if row is None and settings.meli_access_token and settings.meli_refresh_token and settings.meli_token_encryption_key:
            cipher = self._cipher()
            row = MarketplaceOAuthCredential(provider=PROVIDER, encrypted_access_token=cipher.encrypt(settings.meli_access_token),
                                               encrypted_refresh_token=cipher.encrypt(settings.meli_refresh_token), version=1)
            self.db.add(row)
        if row:
            row.credential_status = status
            row.refresh_not_before = self._now() + timedelta(seconds=retry_after_seconds) if retry_after_seconds else None
            row.updated_at = self._now()
            self._sync_connection(row)
        self._decision(action, status, reason, http_status)
        self.db.commit()

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> int:
        try:
            return max(1, min(int(response.headers.get("Retry-After", "60")), 3600))
        except ValueError:
            return 60

    def _decision(self, action: str, status: str, reason: str, http_status: int | None = None, expires_at: datetime | None = None) -> None:
        self.db.add(DecisionLog(actor="SYSTEM", entity_type="MARKETPLACE_CONNECTION", entity_id=None, action=action,
                                reason=None, metadata_={"provider": PROVIDER, "status": status, "errorCode": reason,
                                                       "httpStatus": http_status,
                                                       "expiresAt": expires_at.isoformat() if expires_at else None}))
