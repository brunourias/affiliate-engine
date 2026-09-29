import base64
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from apps.api.app.core.config import settings
from apps.api.app.db.models import DecisionLog, MarketplaceConnection, MarketplaceOAuthCredential
from apps.api.app.db.session import SessionLocal
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.integrations.mercado_livre.oauth import MercadoLivreAuthError, MercadoLivreTokenManager, TokenCipher

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()


@pytest.fixture(autouse=True)
def oauth_settings(monkeypatch):
    monkeypatch.setattr(settings, "meli_client_id", "client-id")
    monkeypatch.setattr(settings, "meli_client_secret", "client-secret")
    monkeypatch.setattr(settings, "meli_access_token", "bootstrap-access")
    monkeypatch.setattr(settings, "meli_refresh_token", "bootstrap-refresh")
    monkeypatch.setattr(settings, "meli_token_encryption_key", KEY)
    monkeypatch.setattr(settings, "meli_token_refresh_margin_seconds", 300)


def transport(handler):
    return httpx.MockTransport(handler)


def token_response(access="access-b", refresh="refresh-b", expires=21600):
    return httpx.Response(200, json={"access_token": access, "refresh_token": refresh, "expires_in": expires,
                                     "user_id": 44203679, "scope": "offline_access", "token_type": "Bearer"})


def seed(db, access="access-a", refresh="refresh-a", expires_at=None, status="AVAILABLE"):
    cipher = TokenCipher(KEY)
    row = MarketplaceOAuthCredential(provider="MERCADO_LIVRE", external_account_id="44203679",
        encrypted_access_token=cipher.encrypt(access), encrypted_refresh_token=cipher.encrypt(refresh),
        expires_at=expires_at, credential_status=status, version=1)
    db.add(row); db.commit()
    return row


def test_valid_access_token_does_not_refresh_and_public_request_needs_no_token(monkeypatch):
    calls=[]
    with SessionLocal() as db:
        seed(db, expires_at=datetime.now(timezone.utc)+timedelta(hours=2))
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(calls.append(request),token_response())[1]))
        api=[]
        client=MercadoLivreClient(token_manager=manager,transport=transport(lambda request:(api.append(request),httpx.Response(200,json={"ok":True}))[1]))
        assert client.get("AUTH","/users/me",requires_auth=True).status=="AVAILABLE"
        assert api[0].headers["Authorization"]=="Bearer access-a" and calls==[]
        client.close()
    monkeypatch.setattr(settings,"meli_access_token","");monkeypatch.setattr(settings,"meli_refresh_token","")
    client=MercadoLivreClient(transport=transport(lambda request:httpx.Response(200,json={})))
    assert client.get("SITE","/sites/MLB").status=="AVAILABLE"


def test_proactive_refresh_rotates_and_persists_pair_atomically():
    refresh_requests=[]
    with SessionLocal() as db:
        seed(db,expires_at=datetime.now(timezone.utc)+timedelta(seconds=20))
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(refresh_requests.append(request),token_response())[1]))
        assert manager.access_token()=="access-b"
        row=db.scalar(select(MarketplaceOAuthCredential));cipher=TokenCipher(KEY)
        assert cipher.decrypt(row.encrypted_access_token)=="access-b"
        assert cipher.decrypt(row.encrypted_refresh_token)=="refresh-b"
        assert row.last_refresh_at and row.expires_at and row.version==3
        assert refresh_requests[0].read().decode().find("refresh_token=refresh-a") >= 0
        assert "access-b" not in row.encrypted_access_token and "refresh-b" not in row.encrypted_refresh_token
        manager.close()


def test_401_refreshes_once_retries_with_new_token_and_next_request_reuses_it():
    api_tokens=[]; refreshes=[]
    def api(request):
        api_tokens.append(request.headers.get("Authorization"))
        return httpx.Response(401,json={"error":"unauthorized"}) if len(api_tokens)==1 else httpx.Response(200,json={"id":"ok"})
    with SessionLocal() as db:
        seed(db,expires_at=None)
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(refreshes.append(request),token_response())[1]))
        client=MercadoLivreClient(token_manager=manager,transport=transport(api))
        assert client.get("ITEM_DETAILS","/items/MLB849301960",requires_auth=True).status=="AVAILABLE"
        assert client.get("AUTH_USER","/users/me",requires_auth=True).status=="AVAILABLE"
        assert api_tokens==["Bearer access-a","Bearer access-b","Bearer access-b"] and len(refreshes)==1
        client.close()


def test_second_401_does_not_loop_or_refresh_twice():
    refreshes=[]
    with SessionLocal() as db:
        seed(db,expires_at=None)
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(refreshes.append(request),token_response())[1]))
        client=MercadoLivreClient(token_manager=manager,transport=transport(lambda request:httpx.Response(401,json={"error":"unauthorized"})))
        result=client.get("AUTH_USER","/users/me",requires_auth=True)
        assert result.status=="UNAUTHORIZED" and len(refreshes)==1
        assert db.scalar(select(MarketplaceOAuthCredential)).credential_status=="REAUTH_REQUIRED"
        client.close()


def test_403_never_refreshes_and_preserves_sanitized_metadata():
    refreshes=[]
    with SessionLocal() as db:
        seed(db,expires_at=None)
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(refreshes.append(request),token_response())[1]))
        client=MercadoLivreClient(token_manager=manager,transport=transport(lambda request:httpx.Response(403,json={"error":{"code":"access_denied","type":"PA_UNAUTHORIZED_RESULT_FROM_POLICIES"}})))
        result=client.get("ITEM_DETAILS","/items/MLB4759377111",requires_auth=True)
        assert result.status=="FORBIDDEN" and result.metadata["remoteErrorCode"]=="access_denied" and refreshes==[]
        client.close()


def policy_denied():
    return httpx.Response(403,json={"code":"PA_UNAUTHORIZED_RESULT_FROM_POLICIES","blocked_by":"PolicyAgent"})


def test_policy_403_confirmed_by_probe_refreshes_once_and_retries_original():
    paths=[];refreshes=[]
    def api(request):
        paths.append((request.url.path,request.headers.get("Authorization")))
        if len(paths)<=2:return policy_denied()
        return httpx.Response(200,json={"id":"MLB849301960"})
    with SessionLocal() as db:
        seed(db,expires_at=None)
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(refreshes.append(request),token_response())[1]))
        client=MercadoLivreClient(token_manager=manager,transport=transport(api))
        result=client.get("ITEM_DETAILS","/items/MLB849301960",requires_auth=True)
        assert result.status=="AVAILABLE"
        assert paths==[("/items/MLB849301960","Bearer access-a"),("/users/me","Bearer access-a"),("/items/MLB849301960","Bearer access-b")]
        assert len(refreshes)==1
        client.close()


def test_policy_403_with_successful_probe_preserves_original_forbidden():
    paths=[];refreshes=[]
    def api(request):
        paths.append(request.url.path)
        return httpx.Response(200,json={"id":44203679}) if request.url.path=="/users/me" else policy_denied()
    with SessionLocal() as db:
        seed(db,expires_at=None)
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(refreshes.append(request),token_response())[1]))
        client=MercadoLivreClient(token_manager=manager,transport=transport(api))
        result=client.get("ITEM_DETAILS","/items/MLB849301960",requires_auth=True)
        assert result.status=="FORBIDDEN" and paths==["/items/MLB849301960","/users/me"] and refreshes==[]
        client.close()


@pytest.mark.parametrize("probe",[
    httpx.Response(503,json={"code":"temporary"}),
    httpx.Response(429,json={"code":"rate_limited"}),
])
def test_inconclusive_http_auth_probe_is_degraded_without_refresh(probe):
    refreshes=[]
    def api(request):return probe if request.url.path=="/users/me" else policy_denied()
    with SessionLocal() as db:
        seed(db,expires_at=None)
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(refreshes.append(request),token_response())[1]))
        client=MercadoLivreClient(token_manager=manager,transport=transport(api))
        result=client.get("ITEM_DETAILS","/items/MLB849301960",requires_auth=True)
        assert result.status=="DEGRADED" and result.reason_code.startswith("AUTH_PROBE_HTTP_") and refreshes==[]
        client.close()


def test_auth_probe_network_failure_is_degraded_without_refresh():
    refreshes=[]
    def api(request):
        if request.url.path=="/users/me":raise httpx.ReadTimeout("private-token",request=request)
        return policy_denied()
    with SessionLocal() as db:
        seed(db,expires_at=None)
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(refreshes.append(request),token_response())[1]))
        client=MercadoLivreClient(token_manager=manager,transport=transport(api))
        result=client.get("AUTH_USER","/items/MLB849301960",requires_auth=True)
        assert result.status=="DEGRADED" and result.reason_code=="AUTH_PROBE_TIMEOUT" and refreshes==[]
        assert "private-token" not in result.message and "private-token" not in repr(result.metadata)
        client.close()


def test_retry_after_policy_refresh_does_not_probe_or_refresh_again():
    paths=[];refreshes=[]
    def api(request):
        paths.append(request.url.path)
        return policy_denied()
    with SessionLocal() as db:
        seed(db,expires_at=None)
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(refreshes.append(request),token_response())[1]))
        client=MercadoLivreClient(token_manager=manager,transport=transport(api))
        result=client.get("ITEM_DETAILS","/items/MLB849301960",requires_auth=True)
        assert result.status=="FORBIDDEN" and paths==["/items/MLB849301960","/users/me","/items/MLB849301960"]
        assert len(refreshes)==1
        assert db.scalar(select(MarketplaceOAuthCredential)).credential_status=="REAUTH_REQUIRED"
        client.close()


def test_retry_after_policy_refresh_can_return_access_denied_without_second_refresh():
    paths=[];refreshes=[]
    def api(request):
        paths.append(request.url.path)
        if len(paths)<=2:return policy_denied()
        return httpx.Response(403,json={"error":{"code":"access_denied","type":"access_denied"}})
    with SessionLocal() as db:
        seed(db,expires_at=None)
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(refreshes.append(request),token_response())[1]))
        client=MercadoLivreClient(token_manager=manager,transport=transport(api))
        result=client.get("ITEM_DETAILS","/items/MLB4759377111",requires_auth=True)
        assert result.status=="FORBIDDEN" and result.metadata["remoteErrorCode"]=="access_denied" and len(refreshes)==1
        client.close()


def test_concurrent_refresh_is_single_flight_and_both_use_rotated_token():
    refresh_count=0; guard=threading.Lock()
    def refresh_handler(request):
        nonlocal refresh_count
        with guard: refresh_count+=1
        return token_response()
    with SessionLocal() as db: seed(db,expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
    def worker(_):
        with SessionLocal() as db:
            manager=MercadoLivreTokenManager(db,transport=transport(refresh_handler))
            try:return manager.access_token()
            finally:manager.close()
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(worker,range(2)))
    assert results==["access-b","access-b"] and refresh_count==1


@pytest.mark.parametrize(("remote,status,code"),[("invalid_grant","REAUTH_REQUIRED","REAUTH_REQUIRED"),("invalid_client","CONFIGURATION_ERROR","INVALID_CLIENT_CONFIGURATION")])
def test_terminal_refresh_errors_set_safe_status_without_secret(remote,status,code):
    with SessionLocal() as db:
        seed(db,expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:httpx.Response(400,json={"error":remote,"message":"contains refresh-a"})))
        with pytest.raises(MercadoLivreAuthError) as caught: manager.access_token()
        row=db.scalar(select(MarketplaceOAuthCredential)); logs=db.scalars(select(DecisionLog)).all()
        assert caught.value.code==code and row.credential_status==status
        assert "refresh-a" not in str(caught.value) and "refresh-a" not in repr([x.metadata_ for x in logs])
        manager.close()


@pytest.mark.parametrize("response",[httpx.Response(429,json={"error":"too_many_requests"}),httpx.Response(503,text="secret remote body")])
def test_temporary_refresh_failure_is_degraded_and_preserves_credential(response):
    with SessionLocal() as db:
        row=seed(db,expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)); old=(row.encrypted_access_token,row.encrypted_refresh_token)
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:response))
        with pytest.raises(MercadoLivreAuthError) as caught:manager.access_token()
        db.refresh(row)
        assert caught.value.temporary and row.credential_status=="DEGRADED"
        assert (row.encrypted_access_token,row.encrypted_refresh_token)==old
        manager.close()


def test_network_error_preserves_credential():
    with SessionLocal() as db:
        row=seed(db,expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)); old=row.encrypted_refresh_token
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(_ for _ in ()).throw(httpx.ConnectError("network",request=request))))
        with pytest.raises(MercadoLivreAuthError):manager.access_token()
        db.refresh(row);assert row.encrypted_refresh_token==old and row.credential_status=="DEGRADED"
        manager.close()


def test_refresh_timeout_is_safe_degraded_and_does_not_expose_tokens(caplog):
    with SessionLocal() as db:
        seed(db,expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:(_ for _ in ()).throw(httpx.ReadTimeout("refresh-a",request=request))))
        with caplog.at_level(logging.INFO), pytest.raises(MercadoLivreAuthError) as caught:manager.access_token()
        assert caught.value.code=="TOKEN_REFRESH_DEGRADED"
        assert "refresh-a" not in str(caught.value) and "refresh-a" not in caplog.text
        manager.close()


def test_persisted_credential_wins_over_old_environment_after_logical_restart(monkeypatch):
    with SessionLocal() as db: seed(db,access="managed-access",refresh="managed-refresh",expires_at=None)
    monkeypatch.setattr(settings,"meli_access_token","old-env-access");monkeypatch.setattr(settings,"meli_refresh_token","old-env-refresh")
    with SessionLocal() as db:
        manager=MercadoLivreTokenManager(db);assert manager.access_token()=="managed-access" and manager.auth_mode=="OAUTH_MANAGED";manager.close()


def test_bootstrap_first_refresh_creates_encrypted_managed_record():
    with SessionLocal() as db:
        manager=MercadoLivreTokenManager(db,transport=transport(lambda request:token_response()))
        assert manager.refresh_after_unauthorized("bootstrap-access")=="access-b"
        row=db.scalar(select(MarketplaceOAuthCredential));assert row and row.credential_status=="AVAILABLE"
        assert manager.public_status()["authMode"]=="OAUTH_MANAGED"
        manager.close()


def test_public_auth_status_and_connection_metadata_never_expose_secrets(client):
    with SessionLocal() as db:
        seed(db,expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
        db.add(MarketplaceConnection(provider="MERCADO_LIVRE",site_id="MLB",status="AVAILABLE",auth_mode="OAUTH_MANAGED",metadata_={"authStatus":"AVAILABLE"}));db.commit()
    response=client.get("/api/v1/marketplaces/mercado-livre/auth")
    serialized=response.text
    assert response.status_code==200 and response.json()["authMode"]=="OAUTH_MANAGED"
    for secret in ("managed-access","refresh-a","bootstrap-access","bootstrap-refresh",KEY): assert secret not in serialized
