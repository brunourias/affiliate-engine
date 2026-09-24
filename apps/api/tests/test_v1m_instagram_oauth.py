import json
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select,text
from apps.api.app.core.config import settings
from apps.api.app.db.models import DecisionLog,OAuthState,PublicationConnection
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.instagram_oauth import InstagramConnectionService,InstagramOAuthClient,InstagramOAuthError,PROFILE,state_hash
from apps.api.app.services.publication_connectors import InstagramPublicationConnector,TikTokPublicationConnector

class FakeStore:
    def __init__(self,available=True):self.items={};self.ok=available
    def available(self):return self.ok
    def store(self,reference,token):self.items[reference]=token
    def load(self,reference):return self.items[reference]
    def delete(self,reference):self.items.pop(reference,None)
    def metadata(self,reference):return {"reference":reference,"available":self.ok}
class FakeClient:
    def __init__(self,account_type="BUSINESS",scopes=None):self.account_type=account_type;self.scopes=scopes or PROFILE["requiredScopes"]
    def build_authorization_url(self,state):return InstagramOAuthClient().build_authorization_url(state)
    def exchange_code(self,code):return {"access_token":"ultra-secret-token","expires_in":3600,"permissions":self.scopes}
    def fetch_account(self,token):assert token=="ultra-secret-token";return {"user_id":"ig-1","username":"loja_teste","account_type":self.account_type}
    def validate_token(self,token):return self.fetch_account(token)

@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings,"instagram_client_id","client-123");monkeypatch.setattr(settings,"instagram_client_secret","client-secret-never-return");monkeypatch.setattr(settings,"instagram_redirect_uri","http://localhost/callback")

def service(store=None,client=None):return InstagramConnectionService(SessionLocal(),store or FakeStore(),client or FakeClient())
def authorize_and_callback(svc,account_type="BUSINESS"):
    result=svc.authorize();state=result["authorizationUrl"].split("state=")[1];return svc.callback(state,"authorization-code")

def test_authorization_url_minimum_scopes_random_state(configured):
    svc=service();first=svc.authorize();second=svc.authorize();assert "client_id=client-123" in first["authorizationUrl"]
    assert "instagram_business_basic" in first["authorizationUrl"] and "instagram_business_content_publish" in first["authorizationUrl"]
    assert "manage_messages" not in first["authorizationUrl"] and "manage_comments" not in first["authorizationUrl"] and first["authorizationUrl"]!=second["authorizationUrl"]

def test_invalid_expired_reused_and_missing_code(configured):
    svc=service()
    with pytest.raises(InstagramOAuthError,match="inválida"):svc.callback("invalid","code")
    raw="expired";svc.db.add(OAuthState(state_hash=state_hash(raw),provider="INSTAGRAM",expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)));svc.db.commit()
    with pytest.raises(InstagramOAuthError,match="expirou"):svc.callback(raw,"code")
    raw=svc.authorize()["authorizationUrl"].split("state=")[1]
    with pytest.raises(InstagramOAuthError,match="não retornou"):svc.callback(raw,None)
    with pytest.raises(InstagramOAuthError,match="já foi utilizada"):svc.callback(raw,"code")

def test_user_denied_is_safe(configured):
    svc=service();raw=svc.authorize()["authorizationUrl"].split("state=")[1]
    with pytest.raises(InstagramOAuthError,match="cancelada"):svc.callback(raw,None,"access_denied")

@pytest.mark.parametrize("account_type",["BUSINESS","CREATOR"])
def test_professional_account_connected_without_secret_leaks(configured,account_type,caplog):
    store=FakeStore();svc=service(store,FakeClient(account_type));result=authorize_and_callback(svc);payload=json.dumps(result,default=str);assert result["status"]=="CONNECTED" and result["accountType"]==account_type
    assert "ultra-secret-token" not in payload and "client-secret-never-return" not in payload and store.items
    with SessionLocal() as db:
        raw="\n".join(str(row) for row in db.execute(text("select * from publication_connections")).all());logs=json.dumps([x.metadata_ for x in db.scalars(select(DecisionLog)).all()],default=str)
        assert "ultra-secret-token" not in raw+logs and "authorization-code" not in raw+logs

def test_non_professional_and_missing_scope_block_readiness(configured):
    svc=service(client=FakeClient("PERSONAL"));assert authorize_and_callback(svc)["status"]=="ACCOUNT_NOT_SUPPORTED"
    svc.db.query(PublicationConnection).delete();svc.db.commit();svc=InstagramConnectionService(svc.db,FakeStore(),FakeClient("BUSINESS",["instagram_business_basic"]));result=authorize_and_callback(svc);assert result["status"]=="INSUFFICIENT_SCOPE" and result["publicationConnectorReadiness"]=="NOT_READY"

def test_secure_store_unavailable_blocks(configured):
    svc=service(FakeStore(False));assert svc.readiness()["checks"]["SECURE_TOKEN_STORE_AVAILABLE"] is False
    with pytest.raises(InstagramOAuthError) as exc:svc.authorize()
    assert exc.value.code=="secure_storage_unavailable"

def test_validate_expiry_and_disconnect(configured):
    store=FakeStore();svc=service(store);authorize_and_callback(svc);before=svc.connection().last_validated_at;result=svc.validate();assert result["status"]=="CONNECTED" and svc.connection().last_validated_at>=before
    svc.connection().expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);svc.db.commit();assert svc.validate()["status"]=="EXPIRED"
    result=svc.disconnect();assert result["status"]=="AUTHENTICATION_REQUIRED" and not store.items and svc.connection().token_store_reference is None

def test_connector_removes_only_connection_blocker():
    connection={"status":"CONNECTED","accountType":"BUSINESS","accountId":"ig-1","scopes":PROFILE["requiredScopes"]};connector=InstagramPublicationConnector("DIRECT_PUBLISH",connection=connection);assert connector.validate_connection()["reasonCodes"]==[]
    package={"publicationCandidateId":"pc","packageFingerprint":"fp","format":"CAROUSEL","assetFiles":["a"],"manualReviewRequired":True};result=connector.validate_package(package,"LOCAL_ONLY","BUSINESS",True);assert "INSTAGRAM_CONNECTION_REQUIRED" not in result["reasonCodes"] and {"PUBLIC_MEDIA_SOURCE_REQUIRED","DISCLOSURE_REQUIREMENT_UNKNOWN"}<=set(result["reasonCodes"])
    assert TikTokPublicationConnector("DIRECT_PUBLISH").validate_connection()["status"]=="NOT_CONFIGURED"

def test_phase_one_readiness_without_configuration(monkeypatch):
    monkeypatch.setattr(settings,"instagram_client_id","");monkeypatch.setattr(settings,"instagram_client_secret","");monkeypatch.setattr(settings,"instagram_redirect_uri","");result=service().readiness();assert result["status"]=="NOT_CONFIGURED" and not result["checks"]["CLIENT_ID_CONFIGURED"] and not result["checks"]["REDIRECT_URI_CONFIGURED"]
