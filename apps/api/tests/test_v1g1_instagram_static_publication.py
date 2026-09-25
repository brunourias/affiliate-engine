import json,logging,threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from sqlalchemy import select
from apps.api.app.core.config import settings
from apps.api.app.db.models import AppSettings,Creative,DecisionLog,PublicationConnection,PublicationExecution
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.instagram_publishing import InstagramPublishError,InstagramStaticPublisher
from apps.api.tests.test_v1e_creatives import campaign

class FakeStore:
    def available(self):return True
    def load(self,reference):assert reference=="credential-ref";return "secret-test-token"
    def store(self,*args):pass
    def delete(self,*args):pass
    def metadata(self,*args):return {}
class FakeClient:
    def __init__(self,fail=None):self.calls=[];self.fail=fail
    def publishing_limit(self,account_id,token):self.calls.append(("limit",account_id,token));return {"quota_usage":1,"config":{"quota_total":50}}
    def create_image_container(self,account_id,image_url,caption,token):
        self.calls.append(("container",account_id,image_url,caption,token))
        if self.fail=="container":raise InstagramPublishError("INSTAGRAM_API_ERROR","safe",502)
        return "container-1"
    def publish_container(self,account_id,container_id,token):
        self.calls.append(("publish",account_id,container_id,token))
        if self.fail=="publish":raise InstagramPublishError("INSTAGRAM_API_TIMEOUT","safe timeout",504)
        return "media-1"
class BlockingFakeClient(FakeClient):
    def __init__(self):super().__init__();self.entered=threading.Event();self.release=threading.Event()
    def publishing_limit(self,account_id,token):
        self.calls.append(("limit",account_id,token));self.entered.set();assert self.release.wait(5);return {"quota_usage":1,"config":{"quota_total":50}}

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));candidate="candidate-1"
    campaign_id=campaign()
    with SessionLocal() as db:
        creative=Creative(campaign_id=campaign_id,name="Static",status="APPROVED",content_type="STATIC_POST",target_channel="INSTAGRAM_REELS",objective_snapshot="CONVERSION",editorial_verdict_snapshot="WORTH_IT",price_verdict_snapshot="FAIR_PRICE",cta="Veja os detalhes",disclosure_text="Link de afiliado",required_warnings=[],forbidden_claims=[]);db.add(creative);db.add(PublicationConnection(channel="INSTAGRAM",connector="INSTAGRAM_CONTENT_PUBLISHING",status="CONNECTED",account_id="ig-1",account_type="CREATOR",username="test",scopes=["instagram_business_basic","instagram_business_content_publish"],auth_profile="INSTAGRAM_LOGIN_CONTENT_PUBLISH_V1",token_store_reference="credential-ref"));config=db.get(AppSettings,1);config.system_automation_enabled=True;config.publishing_enabled=True;db.commit();creative_id=creative.id
    package={"creativeId":creative_id,"publicationCandidateId":candidate,"packageFingerprint":"f"*64,"channel":"INSTAGRAM","format":"STATIC_CARD","assetFiles":["static/card.png"],"readinessStatus":"READY","blockers":[],"disclosurePlan":{"status":"PRESENT","displayText":"Link de afiliado"}}
    delivery={"publicationCandidateId":candidate,"format":"STATIC_CARD","readiness":"READY","hostedAssets":[{"publicUrl":"https://media.example.com/api/v1/public-media/a?token=signed","contentType":"image/png","status":"AVAILABLE","expiresAt":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}]}
    write_manifests(tmp_path,creative_id,candidate,package,delivery);return creative_id,candidate,package,delivery,tmp_path

def write_manifests(root,creative,candidate,package,delivery):
    package_path=Path(root)/"publication_packages"/creative/candidate;package_path.mkdir(parents=True,exist_ok=True);(package_path/"manifest.json").write_text(json.dumps(package),encoding="utf-8")
    delivery_path=Path(root)/"public_delivery"/"manifests"/candidate;delivery_path.mkdir(parents=True,exist_ok=True);(delivery_path/"media-delivery-manifest.json").write_text(json.dumps(delivery),encoding="utf-8")
def publish(prepared,fake=None):
    creative,candidate,*_=prepared;db=SessionLocal();client=fake or FakeClient();return db,client,InstagramStaticPublisher(db,client,FakeStore()).publish(creative,candidate,True)

def test_requires_explicit_confirmation_without_remote(prepared):
    creative,candidate,*_=prepared;fake=FakeClient()
    with SessionLocal() as db,pytest.raises(InstagramPublishError) as exc:InstagramStaticPublisher(db,fake,FakeStore()).publish(creative,candidate,False)
    assert exc.value.code=="EXPLICIT_CONFIRMATION_REQUIRED" and fake.calls==[]

@pytest.mark.parametrize(("field","value","code"),[("system_automation_enabled",False,"KILL_SWITCH_ACTIVE"),("publishing_enabled",False,"PUBLISHING_DISABLED")])
def test_switches_block_before_remote(prepared,field,value,code):
    creative,candidate,*_=prepared;fake=FakeClient()
    with SessionLocal() as db:
        setattr(db.get(AppSettings,1),field,value);db.commit()
        with pytest.raises(InstagramPublishError) as exc:InstagramStaticPublisher(db,fake,FakeStore()).publish(creative,candidate,True)
    assert exc.value.code==code and fake.calls==[]

def test_unapproved_and_package_blockers_prevent_remote(prepared):
    creative,candidate,package,delivery,root=prepared;fake=FakeClient()
    with SessionLocal() as db:db.get(Creative,creative).status="DRAFT";db.commit()
    with SessionLocal() as db,pytest.raises(InstagramPublishError) as exc:InstagramStaticPublisher(db,fake,FakeStore()).publish(creative,candidate,True)
    assert exc.value.code=="CREATIVE_NOT_APPROVED" and not fake.calls
    with SessionLocal() as db:db.get(Creative,creative).status="APPROVED";db.commit()
    package["readinessStatus"]="BLOCKED";package["blockers"]=[{"code":"X"}];write_manifests(root,creative,candidate,package,delivery)
    with SessionLocal() as db,pytest.raises(InstagramPublishError) as exc:InstagramStaticPublisher(db,fake,FakeStore()).publish(creative,candidate,True)
    assert exc.value.code=="PUBLICATION_PACKAGE_NOT_READY" and not fake.calls

@pytest.mark.parametrize(("account_type","scopes","status","code"),[("CREATOR",[],"CONNECTED","INSTAGRAM_PERMISSION_REQUIRED"),("PERSONAL",["instagram_business_content_publish"],"CONNECTED","ACCOUNT_NOT_SUPPORTED"),("CREATOR",["instagram_business_content_publish"],"AUTHENTICATION_REQUIRED","INSTAGRAM_CONNECTION_REQUIRED")])
def test_connection_account_and_scope_gates(prepared,account_type,scopes,status,code):
    creative,candidate,*_=prepared;fake=FakeClient()
    with SessionLocal() as db:row=db.scalar(select(PublicationConnection));row.account_type=account_type;row.scopes=scopes;row.status=status;db.commit()
    with SessionLocal() as db,pytest.raises(InstagramPublishError) as exc:InstagramStaticPublisher(db,fake,FakeStore()).publish(creative,candidate,True)
    assert exc.value.code==code and not fake.calls

def test_missing_account_id_blocks_before_remote(prepared):
    creative,candidate,*_=prepared;fake=FakeClient()
    with SessionLocal() as db:row=db.scalar(select(PublicationConnection));row.account_id=None;db.commit()
    with SessionLocal() as db,pytest.raises(InstagramPublishError) as exc:InstagramStaticPublisher(db,fake,FakeStore()).publish(creative,candidate,True)
    assert exc.value.code=="INSTAGRAM_ACCOUNT_ID_REQUIRED" and not fake.calls

@pytest.mark.parametrize(("format","assets","code"),[("VIDEO_SHORT",["a.mp4"],"FORMAT_NOT_SUPPORTED"),("CAROUSEL",["a.png"],"FORMAT_NOT_SUPPORTED"),("STATIC_CARD",["a.png","b.png"],"SINGLE_IMAGE_REQUIRED")])
def test_only_one_static_image(prepared,format,assets,code):
    creative,candidate,package,delivery,root=prepared;package["format"]=format;package["assetFiles"]=assets;write_manifests(root,creative,candidate,package,delivery);fake=FakeClient()
    with SessionLocal() as db,pytest.raises(InstagramPublishError) as exc:InstagramStaticPublisher(db,fake,FakeStore()).publish(creative,candidate,True)
    assert exc.value.code==code and not fake.calls

def test_non_public_delivery_blocks(prepared):
    creative,candidate,package,delivery,root=prepared;delivery["hostedAssets"][0]["publicUrl"]="http://127.0.0.1/media.png";write_manifests(root,creative,candidate,package,delivery);fake=FakeClient()
    with SessionLocal() as db,pytest.raises(InstagramPublishError) as exc:InstagramStaticPublisher(db,fake,FakeStore()).publish(creative,candidate,True)
    assert exc.value.code=="PUBLIC_MEDIA_SOURCE_REQUIRED" and not fake.calls

def test_container_publish_idempotency_audit_and_secret_redaction(prepared,caplog):
    caplog.set_level(logging.INFO);db,fake,result=publish(prepared);assert result["status"]=="PUBLISHED" and result["platformMediaId"]=="media-1" and result["remoteRequestExecuted"] is True
    assert [x[0] for x in fake.calls]==["limit","container","publish"] and fake.calls[1][2].startswith("https://media.example.com/")
    again=InstagramStaticPublisher(db,fake,FakeStore()).publish(prepared[0],prepared[1],True);assert again==result and len(fake.calls)==3
    actions=set(db.scalars(select(DecisionLog.action)).all());assert {"INSTAGRAM_PUBLICATION_REQUESTED","INSTAGRAM_CONTAINER_CREATED","INSTAGRAM_PUBLICATION_SUCCEEDED"}<=actions
    serialized=json.dumps(result,default=str)+json.dumps([x.metadata_ for x in db.scalars(select(DecisionLog)).all()],default=str)+caplog.text
    assert "secret-test-token" not in serialized and "access_token" not in serialized.lower();db.close()

def test_concurrent_attempts_acquire_execution_once_and_run_one_remote_sequence(prepared):
    fake=BlockingFakeClient();results=[]
    def first():
        with SessionLocal() as db:results.append(InstagramStaticPublisher(db,fake,FakeStore()).publish(prepared[0],prepared[1],True))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(first);assert fake.entered.wait(5)
        second_client=FakeClient()
        with SessionLocal() as db,pytest.raises(InstagramPublishError) as exc:InstagramStaticPublisher(db,second_client,FakeStore()).publish(prepared[0],prepared[1],True)
        assert exc.value.code=="EXECUTION_ALREADY_ATTEMPTED" and second_client.calls==[]
        fake.release.set();future.result(timeout=5)
    assert [x[0] for x in fake.calls]==["limit","container","publish"] and results[0]["status"]=="PUBLISHED"
    with SessionLocal() as db:assert db.scalar(select(DecisionLog).where(DecisionLog.action=="INSTAGRAM_PUBLICATION_REQUESTED")) is not None and len(db.scalars(select(DecisionLog).where(DecisionLog.action=="INSTAGRAM_PUBLICATION_REQUESTED")).all())==1

@pytest.mark.parametrize(("failure","expected"),[("container","INSTAGRAM_API_ERROR"),("publish","INSTAGRAM_API_TIMEOUT")])
def test_remote_failure_is_safe_and_not_retried(prepared,failure,expected):
    fake=FakeClient(failure)
    with SessionLocal() as db:
        publisher=InstagramStaticPublisher(db,fake,FakeStore())
        with pytest.raises(InstagramPublishError) as exc:publisher.publish(prepared[0],prepared[1],True)
        assert exc.value.code==expected and "secret-test-token" not in exc.value.message;row=db.scalar(select(PublicationExecution));assert row.status=="FAILED" and row.failure_code==expected and row.remote_request_executed
        before=len(fake.calls)
        with pytest.raises(InstagramPublishError) as second:publisher.publish(prepared[0],prepared[1],True)
        assert second.value.code=="EXECUTION_ALREADY_ATTEMPTED" and len(fake.calls)==before

def test_endpoint_requires_confirmation(client,prepared):
    response=client.post(f"/api/v1/creatives/{prepared[0]}/instagram-publish",json={"confirm":False,"publicationCandidateId":prepared[1]});assert response.status_code==409 and response.json()["detail"]["code"]=="EXPLICIT_CONFIRMATION_REQUIRED"
