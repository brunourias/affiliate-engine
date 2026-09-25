from __future__ import annotations
import ctypes,hashlib,json,logging,os,secrets
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from typing import Protocol
from urllib.parse import urlencode
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.core.config import settings
from apps.api.app.db.models import OAuthState,PublicationConnection
from apps.api.app.services.operations import log_decision

log=logging.getLogger(__name__)
PROFILE={"id":"INSTAGRAM_LOGIN_CONTENT_PUBLISH_V1","loginType":"INSTAGRAM_LOGIN","authorizationEndpoint":"https://www.instagram.com/oauth/authorize","tokenEndpoint":"https://api.instagram.com/oauth/access_token","apiBaseUrl":"https://graph.instagram.com","requiredScopes":["instagram_business_basic","instagram_business_content_publish"],"optionalScopes":[],"pkceSupported":False,"source":"INSTAGRAM_API_WITH_INSTAGRAM_LOGIN","lastReviewedAt":"2026-09-24","profileVersion":"1"}
def utcnow():return datetime.now(timezone.utc)
def state_hash(value:str)->str:return hashlib.sha256(value.encode()).hexdigest()
def normalize_instagram_account_type(value:str|None)->str:
    normalized=(value or "").strip().upper()
    return {"BUSINESS":"BUSINESS","MEDIA_BUSINESS":"BUSINESS","CREATOR":"CREATOR","MEDIA_CREATOR":"CREATOR"}.get(normalized,"UNKNOWN")

class SecureTokenStore(Protocol):
    def available(self)->bool:...
    def store(self,reference:str,token:str)->None:...
    def load(self,reference:str)->str:...
    def delete(self,reference:str)->None:...
    def metadata(self,reference:str)->dict:...

class WindowsCredentialManagerTokenStore:
    CRED_TYPE_GENERIC=1;CRED_PERSIST_LOCAL_MACHINE=2
    class CREDENTIALW(ctypes.Structure):
        _fields_=[("Flags",wintypes.DWORD),("Type",wintypes.DWORD),("TargetName",wintypes.LPWSTR),("Comment",wintypes.LPWSTR),("LastWritten",wintypes.FILETIME),("CredentialBlobSize",wintypes.DWORD),("CredentialBlob",ctypes.POINTER(ctypes.c_ubyte)),("Persist",wintypes.DWORD),("AttributeCount",wintypes.DWORD),("Attributes",ctypes.c_void_p),("TargetAlias",wintypes.LPWSTR),("UserName",wintypes.LPWSTR)]
    def __init__(self):
        self.api=None
        if os.name=="nt":
            try:self.api=ctypes.WinDLL("Advapi32.dll",use_last_error=True)
            except OSError:pass
    def available(self)->bool:return self.api is not None
    def store(self,reference:str,token:str)->None:
        if not self.api:raise RuntimeError("SECURE_STORAGE_UNAVAILABLE")
        blob=token.encode("utf-16-le");buffer=(ctypes.c_ubyte*len(blob)).from_buffer_copy(blob);credential=self.CREDENTIALW(Type=self.CRED_TYPE_GENERIC,TargetName=reference,CredentialBlobSize=len(blob),CredentialBlob=buffer,Persist=self.CRED_PERSIST_LOCAL_MACHINE,UserName="affiliate-engine")
        if not self.api.CredWriteW(ctypes.byref(credential),0):raise RuntimeError("SECURE_STORAGE_UNAVAILABLE")
    def load(self,reference:str)->str:
        if not self.api:raise RuntimeError("SECURE_STORAGE_UNAVAILABLE")
        pointer=ctypes.POINTER(self.CREDENTIALW)()
        if not self.api.CredReadW(reference,self.CRED_TYPE_GENERIC,0,ctypes.byref(pointer)):raise KeyError(reference)
        try:return ctypes.string_at(pointer.contents.CredentialBlob,pointer.contents.CredentialBlobSize).decode("utf-16-le")
        finally:self.api.CredFree(pointer)
    def delete(self,reference:str)->None:
        if self.api:self.api.CredDeleteW(reference,self.CRED_TYPE_GENERIC,0)
    def metadata(self,reference:str)->dict:return {"provider":"WINDOWS_CREDENTIAL_MANAGER","reference":reference,"available":self.available()}

class InstagramOAuthError(Exception):
    def __init__(self,code:str,message:str,status:int=400):super().__init__(message);self.code=code;self.message=message;self.status=status

class InstagramOAuthClient:
    def __init__(self,http_client=None):self.http=http_client
    def build_authorization_url(self,state:str)->str:
        return PROFILE["authorizationEndpoint"]+"?"+urlencode({"client_id":settings.instagram_client_id,"redirect_uri":settings.instagram_redirect_uri,"response_type":"code","scope":",".join(PROFILE["requiredScopes"]),"state":state})
    def _client(self):return self.http or httpx.Client(timeout=settings.instagram_oauth_timeout_seconds)
    def exchange_code(self,code:str)->dict:
        try:
            response=self._client().post(PROFILE["tokenEndpoint"],data={"client_id":settings.instagram_client_id,"client_secret":settings.instagram_client_secret,"grant_type":"authorization_code","redirect_uri":settings.instagram_redirect_uri,"code":code});response.raise_for_status();data=response.json()
        except Exception as exc:raise InstagramOAuthError("token_exchange_failed","Não foi possível concluir a autenticação do Instagram.",502) from exc
        if not data.get("access_token"):raise InstagramOAuthError("token_exchange_failed","Não foi possível concluir a autenticação do Instagram.",502)
        return data
    def fetch_account(self,token:str)->dict:
        try:
            response=self._client().get(PROFILE["apiBaseUrl"]+"/me",params={"fields":"user_id,username,account_type"},headers={"Authorization":f"Bearer {token}"});response.raise_for_status();return response.json()
        except Exception as exc:raise InstagramOAuthError("api_validation_failed","Não foi possível validar a conta do Instagram.",502) from exc
    def validate_token(self,token:str)->dict:return self.fetch_account(token)
    def disconnect(self,token:str)->None:return None
    def refresh_token(self,token:str)->dict:raise NotImplementedError("O fluxo não usa refresh token convencional.")

@dataclass
class ScopeValidator:
    required:tuple[str,...]=tuple(PROFILE["requiredScopes"])
    def missing(self,scopes:list[str])->list[str]:return [scope for scope in self.required if scope not in scopes]

class InstagramConnectionService:
    def __init__(self,db:Session,store:SecureTokenStore|None=None,client:InstagramOAuthClient|None=None):self.db=db;self.store=store or WindowsCredentialManagerTokenStore();self.client=client or InstagramOAuthClient()
    def readiness(self)->dict:
        checks={"CLIENT_ID_CONFIGURED":bool(settings.instagram_client_id),"CLIENT_SECRET_CONFIGURED":bool(settings.instagram_client_secret),"REDIRECT_URI_CONFIGURED":bool(settings.instagram_redirect_uri),"SECURE_TOKEN_STORE_AVAILABLE":self.store.available(),"AUTH_PROFILE_CONFIGURED":bool(PROFILE)}
        return {"status":"READY" if all(checks.values()) else "NOT_CONFIGURED","checks":checks,"authProfile":PROFILE["id"]}
    def connection(self)->PublicationConnection|None:return self.db.scalar(select(PublicationConnection).where(PublicationConnection.channel=="INSTAGRAM"))
    def public(self)->dict:
        row=self.connection();ready=self.readiness()
        if not row:return {"channel":"INSTAGRAM","status":"SECURE_STORAGE_UNAVAILABLE" if not self.store.available() else "NOT_CONFIGURED" if ready["status"]=="NOT_CONFIGURED" else "AUTHENTICATION_REQUIRED","accountDisplayName":None,"accountId":None,"accountType":None,"username":None,"scopes":[],"expiresAt":None,"lastValidatedAt":None,"tokenHealth":"UNKNOWN","authProfile":PROFILE["id"],"appReadiness":ready,"publicationConnectorReadiness":"NOT_READY"}
        status=row.status
        if row.expires_at and self._aware(row.expires_at)<=utcnow():status="EXPIRED"
        missing=ScopeValidator().missing(row.scopes or []);health=self.token_health(row.expires_at)
        account_type=normalize_instagram_account_type(row.account_type)
        return {"channel":row.channel,"connector":row.connector,"status":status,"accountDisplayName":row.account_display_name,"accountId":row.account_id,"accountType":account_type,"username":row.username,"scopes":row.scopes or [],"expiresAt":row.expires_at,"lastValidatedAt":row.last_validated_at,"tokenHealth":health,"authProfile":row.auth_profile,"appReadiness":ready,"publicationConnectorReadiness":"READY" if status=="CONNECTED" and not missing and account_type in {"BUSINESS","CREATOR"} else "NOT_READY"}
    def authorize(self,return_path:str|None=None)->dict:
        readiness=self.readiness()
        if not self.store.available():raise InstagramOAuthError("secure_storage_unavailable","O armazenamento seguro de credenciais não está disponível.",409)
        if readiness["status"]!="READY":raise InstagramOAuthError("not_configured","Configure a URI de callback e as credenciais do Instagram.",409)
        state=secrets.token_urlsafe(32);row=OAuthState(state_hash=state_hash(state),provider="INSTAGRAM",expires_at=utcnow()+timedelta(minutes=settings.instagram_oauth_state_ttl_minutes),return_path=return_path);self.db.add(row);self.db.flush();log_decision(self.db,"OPERATOR","PUBLICATION_CONNECTION","INSTAGRAM_AUTH_STARTED",row.id,metadata={"stateFingerprint":row.state_hash[:12],"authProfile":PROFILE["id"]});self.db.commit();return {"authorizationUrl":self.client.build_authorization_url(state),"expiresAt":row.expires_at}
    def callback(self,state:str|None,code:str|None,error:str|None=None)->dict:
        row=self.db.scalar(select(OAuthState).where(OAuthState.state_hash==state_hash(state or ""),OAuthState.provider=="INSTAGRAM"))
        if not row:raise InstagramOAuthError("invalid_state","A sessão de conexão é inválida.")
        if row.used_at:raise InstagramOAuthError("invalid_state","Esta sessão de conexão já foi utilizada.",409)
        if self._aware(row.expires_at)<=utcnow():raise InstagramOAuthError("expired_state","A sessão de conexão expirou.",409)
        row.used_at=utcnow();self.db.commit()
        if error:self._failed(row,error);raise InstagramOAuthError("user_denied","A conexão com o Instagram foi cancelada.")
        if not code:self._failed(row,"missing_code");raise InstagramOAuthError("missing_code","O Instagram não retornou o código de autorização.")
        try:
            token_data=self.client.exchange_code(code);token=token_data["access_token"];account=self.client.fetch_account(token);scopes=self._scopes(token_data);raw_account_type=str(account.get("account_type") or account.get("accountType") or "").strip().upper();account_type=normalize_instagram_account_type(raw_account_type);missing=ScopeValidator().missing(scopes);status="ACCOUNT_NOT_SUPPORTED" if account_type=="UNKNOWN" else "INSUFFICIENT_SCOPE" if missing else "CONNECTED";reference=f"AffiliateEngine/Instagram/{account.get('user_id') or account.get('id')}"
            self.store.store(reference,token);connection=self.connection() or PublicationConnection(channel="INSTAGRAM",connector="INSTAGRAM_CONTENT_PUBLISHING",auth_profile=PROFILE["id"]);self.db.add(connection);connection.status=status;connection.account_id=str(account.get("user_id") or account.get("id"));connection.username=account.get("username");connection.account_display_name=account.get("username");connection.account_type=account_type;connection.scopes=scopes;connection.issued_at=utcnow();connection.expires_at=utcnow()+timedelta(seconds=int(token_data["expires_in"])) if token_data.get("expires_in") else None;connection.refresh_supported=False;connection.last_validated_at=utcnow();connection.token_store_reference=reference;log_decision(self.db,"SYSTEM","PUBLICATION_CONNECTION","INSTAGRAM_AUTH_COMPLETED",connection.id,metadata={"accountId":connection.account_id,"accountType":account_type,"rawAccountType":raw_account_type,"scopes":scopes,"status":status,"stateFingerprint":row.state_hash[:12]});self.db.commit();return self.public()
        except InstagramOAuthError as exc:self._failed(row,exc.code);raise
        except Exception as exc:self._failed(row,"authentication_failed");raise InstagramOAuthError("api_validation_failed","Não foi possível validar a conta do Instagram.",502) from exc
    def validate(self)->dict:
        row=self.connection()
        if not row or not row.token_store_reference:raise InstagramOAuthError("authentication_required","Conecte uma conta do Instagram.",409)
        if row.expires_at and self._aware(row.expires_at)<=utcnow():row.status="EXPIRED";self.db.commit();return self.public()
        try:account=self.client.validate_token(self.store.load(row.token_store_reference))
        except (KeyError,RuntimeError):row.status="AUTHENTICATION_REQUIRED";self.db.commit();return self.public()
        raw_account_type=str(account.get("account_type") or account.get("accountType") or row.account_type or "").strip().upper();account_type=normalize_instagram_account_type(raw_account_type);row.account_type=account_type;row.username=account.get("username") or row.username;row.account_display_name=row.username;row.last_validated_at=utcnow();missing=ScopeValidator().missing(row.scopes or []);row.status="ACCOUNT_NOT_SUPPORTED" if account_type=="UNKNOWN" else "INSUFFICIENT_SCOPE" if missing else "CONNECTED";log_decision(self.db,"OPERATOR","PUBLICATION_CONNECTION","INSTAGRAM_CONNECTION_VALIDATED",row.id,metadata={"status":row.status,"accountType":row.account_type,"rawAccountType":raw_account_type,"scopes":row.scopes});self.db.commit();return self.public()
    def disconnect(self)->dict:
        row=self.connection()
        if row:
            if row.token_store_reference:self.store.delete(row.token_store_reference)
            row.status="AUTHENTICATION_REQUIRED";row.token_store_reference=None;row.scopes=[];row.expires_at=None;log_decision(self.db,"OPERATOR","PUBLICATION_CONNECTION","INSTAGRAM_DISCONNECTED",row.id,metadata={"accountId":row.account_id});self.db.commit()
        return self.public()
    def _failed(self,state:OAuthState,reason:str):
        safe=reason if reason in {"user_denied","access_denied","missing_code","token_exchange_failed","scope_missing","account_not_professional","api_validation_failed","authentication_failed"} else "oauth_failed"
        log_decision(self.db,"SYSTEM","PUBLICATION_CONNECTION","INSTAGRAM_AUTH_FAILED",state.id,reason="Falha segura no fluxo OAuth.",metadata={"reasonCode":safe,"stateFingerprint":state.state_hash[:12]});self.db.commit()
    @staticmethod
    def _scopes(data:dict)->list[str]:
        value=data.get("permissions") or data.get("scope") or []
        return list(dict.fromkeys(value.split(",") if isinstance(value,str) else value))
    @staticmethod
    def _aware(value:datetime)->datetime:return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    @staticmethod
    def token_health(expires:datetime|None)->str:
        if not expires:return "UNKNOWN"
        remaining=InstagramConnectionService._aware(expires)-utcnow()
        return "EXPIRED" if remaining.total_seconds()<=0 else "EXPIRING_SOON" if remaining<=timedelta(days=settings.instagram_token_expiring_soon_days) else "VALID"
