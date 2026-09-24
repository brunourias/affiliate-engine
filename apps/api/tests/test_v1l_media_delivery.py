from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
from pathlib import Path
import pytest
from apps.api.app.core.config import settings
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.media_delivery import MediaDeliveryCleaner,MediaDeliveryEngine,MediaDeliveryStrategyResolver,PublicMediaReachabilityValidator,SignedTemporaryMediaProvider,digest,resumable_upload_plan
from apps.api.app.services.publication_connectors import InstagramPublicationConnector
from apps.api.app.core.logging import SensitiveQueryFilter
import logging
from apps.api.tests.test_v1i_channel_adaptation import source_carousel

def sources(tmp_path):
    cid=source_carousel(tmp_path);root=Path(settings.media_root)/"static"/cid/"carousel";manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));return cid,[f"static/{cid}/carousel/{x['file']}" for x in manifest["cards"]]

def test_resolver_instagram_images_and_reel_plan(tmp_path):
    _,assets=sources(tmp_path);resolver=MediaDeliveryStrategyResolver();assert resolver.resolve("INSTAGRAM","INSTAGRAM_CONTENT_PUBLISHING","CAROUSEL","image/png",10,False)=="TEMPORARY_PUBLIC_URL";assert resolver.resolve("INSTAGRAM","INSTAGRAM_CONTENT_PUBLISHING","VIDEO_SHORT","video/mp4",10,True,True)=="RESUMABLE_UPLOAD"
    path=Path(settings.media_root)/"clip.mp4";path.write_bytes(b"video");plan=resumable_upload_plan("clip.mp4");assert plan["status"]=="PLANNED" and plan["remoteRequestExecuted"] is False

def test_unconfigured_plan_has_three_ordered_assets_and_is_deterministic(tmp_path):
    _,assets=sources(tmp_path)
    with SessionLocal() as db:
        provider=SignedTemporaryMediaProvider(db,base_url="",secret="");engine=MediaDeliveryEngine(db,provider);first=engine.plan("pc","INSTAGRAM","CAROUSEL",assets);same=engine.plan("pc","INSTAGRAM","CAROUSEL",assets)
    assert first["readiness"]=="NOT_READY" and first["strategy"]=="TEMPORARY_PUBLIC_URL" and len(first["assets"])==3 and [x["sourcePath"] for x in first["assets"]]==assets and first["fingerprint"]==same["fingerprint"]
    assert "PUBLIC_MEDIA_BASE_NOT_CONFIGURED" in first["requirements"]

def test_local_stage_checksum_immutability_and_manifest_secret_safety(tmp_path):
    _,assets=sources(tmp_path);secret="test-signing-secret"
    with SessionLocal() as db:result=MediaDeliveryEngine(db,SignedTemporaryMediaProvider(db,"http://127.0.0.1:8000",secret,60,True)).prepare("pc","INSTAGRAM","CAROUSEL",assets)
    assert result["readiness"]=="NOT_READY" and len(result["hostedAssets"])==3 and all(x["reachability"]=="LOCAL_ONLY" for x in result["hostedAssets"])
    for source,hosted in zip(assets,result["hostedAssets"]):assert hosted["checksum"]==digest(Path(settings.media_root)/source)==digest(Path(settings.media_root)/hosted["stagedPath"])
    manifest=(Path(settings.media_root)/"public_delivery/manifests/pc/media-delivery-manifest.json").read_text(encoding="utf-8");assert secret not in manifest

def test_signed_get_head_wrong_cross_asset_expired_revoked_and_path_traversal(tmp_path,client,monkeypatch):
    _,assets=sources(tmp_path);secret="test-signing-secret";monkeypatch.setattr(settings,"public_media_signing_secret",secret)
    provider=SignedTemporaryMediaProvider(base_url="http://127.0.0.1:8000",secret=secret,development=True);one=provider.stage(assets[0]);two=provider.stage(assets[1]);token=one["publicUrl"].split("token=",1)[1]
    assert client.get(f"/api/v1/public-media/{one['id']}?token={token}").status_code==200 and client.head(f"/api/v1/public-media/{one['id']}?token={token}").status_code==200
    assert client.get(f"/api/v1/public-media/{one['id']}?token=bad").status_code==404 and client.get(f"/api/v1/public-media/{two['id']}?token={token}").status_code==404
    expired=SignedTemporaryMediaProvider._token(one["id"],int((datetime.now(timezone.utc)-timedelta(seconds=1)).timestamp()),secret);assert client.get(f"/api/v1/public-media/{one['id']}?token={expired}").status_code==404
    with SessionLocal() as db:MediaDeliveryEngine(db,provider).revoke(one["id"])
    assert client.get(f"/api/v1/public-media/{one['id']}?token={token}").status_code==410 and client.get("/api/v1/public-media/..%2Fsecret?token=x").status_code in {404,422}

def test_reachability_public_https_private_and_http():
    validator=PublicMediaReachabilityValidator();assert validator.validate("")=="UNCONFIGURED" and validator.validate("http://localhost:8000")=="LOCAL_ONLY" and validator.validate("https://10.0.0.2")=="LOCAL_ONLY" and validator.validate("http://media.example.com")=="HTTPS_REQUIRED" and validator.validate("https://media.example.com")=="VALID"

def test_cleanup_removes_staged_not_source_and_source_change_updates_fingerprint(tmp_path):
    _,assets=sources(tmp_path);source=Path(settings.media_root)/assets[0]
    with SessionLocal() as db:
        provider=SignedTemporaryMediaProvider(db,"http://localhost:8000","secret",1,True);hosted=provider.stage(assets[0],ttl_minutes=-1);before=MediaDeliveryEngine(db,provider).plan("pc","INSTAGRAM","CAROUSEL",assets);source.write_bytes(source.read_bytes()+b"x");after=MediaDeliveryEngine(db,provider).plan("pc","INSTAGRAM","CAROUSEL",assets);clean=MediaDeliveryCleaner(db).clean()
    assert before["fingerprint"]!=after["fingerprint"] and hosted["id"] in clean["removed"] and source.exists()

def test_instagram_only_resolves_public_requirement_for_valid_external_delivery():
    package={"publicationCandidateId":"pc","packageFingerprint":"fp","format":"CAROUSEL","assetFiles":["a"],"manualReviewRequired":False};connector=InstagramPublicationConnector("DIRECT_PUBLISH")
    local={"strategy":"TEMPORARY_PUBLIC_URL","readiness":"NOT_READY","provider":{"reachability":"LOCAL_ONLY"}};public={"strategy":"TEMPORARY_PUBLIC_URL","readiness":"READY","provider":{"reachability":"VALID"}}
    assert "PUBLIC_MEDIA_SOURCE_REQUIRED" in connector.validate_package(package,local,"BUSINESS",True)["reasonCodes"] and "PUBLIC_MEDIA_SOURCE_REQUIRED" not in connector.validate_package(package,public,"BUSINESS",True)["reasonCodes"]

def test_signed_token_is_redacted_from_logs():
    record=logging.LogRecord("test",logging.INFO,"",0,'GET /public-media/id?token=complete-secret-token',(),None);SensitiveQueryFilter().filter(record);assert "complete-secret-token" not in record.getMessage() and "[REDACTED]" in record.getMessage()
