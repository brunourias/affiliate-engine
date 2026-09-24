import json
from pathlib import Path
import pytest
from apps.api.app.core.config import settings
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.publication_connectors import CaptionComposer,EnvironmentCredentialProvider,LocalExportPublicationConnector,PublicationConnectorRegistry,PublicationExecutionPlanner,TikTokPublicationConnector,YouTubePublicationConnector
from apps.api.app.services.publication_readiness import PublicationReadinessEngine
from apps.api.tests.test_v1j_publication_readiness import ready_creative

def package(tmp_path):
    creative_id=ready_creative(tmp_path);audio={"mode":"PLATFORM","sourceType":"TIKTOK_CML","selectionRequiredAtPublication":True};disclosure={"affiliateRelationship":"AFFILIATE_LINK","requirementStatus":"UNKNOWN","status":"PRESENT","text":"Este conteúdo contém link de afiliado.","placement":"CAPTION"}
    with SessionLocal() as db:return creative_id,PublicationReadinessEngine(db).prepare(creative_id,audio_plan=audio,disclosure_plan=disclosure)

def test_registry_modes_and_unknown_connector(tmp_path):
    with SessionLocal() as db:
        registry=PublicationConnectorRegistry(db);assert isinstance(registry.resolve("TIKTOK","EXPORT_ONLY"),LocalExportPublicationConnector);assert isinstance(registry.resolve("TIKTOK","ASSISTED_UPLOAD"),TikTokPublicationConnector);assert registry.resolve("UNKNOWN","DIRECT_PUBLISH") is None
        options=registry.options("TIKTOK");assert [x["readiness"] for x in options]==["READY","NOT_CONFIGURED","NOT_CONFIGURED"] and options[0]["actionEnabled"]

def test_tiktok_capabilities_keep_content_and_ads_separate():
    assisted=TikTokPublicationConnector("ASSISTED_UPLOAD");direct=TikTokPublicationConnector("DIRECT_PUBLISH");caps=assisted.capabilities()
    assert caps["connectorDomain"]=="CONTENT_PUBLISHING" and caps["adsManagementSupported"] is False and caps["supportsPhotos"] is True and caps["requiredScopes"]==["video.upload"]
    assert direct.capabilities()["requiredScopes"]==["video.publish"] and direct.validate_connection()["status"]=="NOT_CONFIGURED"
    with pytest.raises(PermissionError):direct.publish({})

def test_youtube_is_separate_and_credentials_never_return_values(monkeypatch):
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET","super-secret");description=EnvironmentCredentialProvider().describe("TIKTOK")
    assert "super-secret" not in json.dumps(description) and YouTubePublicationConnector("DIRECT_PUBLISH").capabilities()["source"]=="YOUTUBE_DATA_API_VIDEOS_INSERT"

def test_caption_preserves_disclosure_and_invents_nothing():
    value=CaptionComposer().compose("Veja os detalhes",{"text":"Link de afiliado"},[],[]);assert "Link de afiliado" in value["text"] and value["hashtags"]==[] and "#" not in value["text"]

def test_execution_fingerprint_is_deterministic_and_changes_with_package():
    planner=PublicationExecutionPlanner();base={"publicationCandidateId":"pc","packageFingerprint":"a","channel":"TIKTOK"};first=planner.create(base,"LOCAL_EXPORT","EXPORT_ONLY");same=planner.create(base,"LOCAL_EXPORT","EXPORT_ONLY");changed=planner.create({**base,"packageFingerprint":"b"},"LOCAL_EXPORT","EXPORT_ONLY")
    assert first["executionFingerprint"]==same["executionFingerprint"]!=changed["executionFingerprint"] and first["remoteRequestExecuted"] is False

def test_export_bundle_contains_expected_files_pending_actions_and_no_secrets(tmp_path):
    creative_id,prepared=package(tmp_path)
    with SessionLocal() as db:bundle=LocalExportPublicationConnector(db).prepare(prepared);duplicate=LocalExportPublicationConnector(db).prepare(prepared)
    root=Path(settings.media_root)/"publication_exports"/creative_id/bundle["executionId"]
    assert bundle["status"]=="EXPORTED" and bundle["executionId"]==duplicate["executionId"] and len(bundle["assets"])==3
    assert all((root/name).is_file() for name in ["manifest.json","caption.txt","destination.txt","disclosure.txt","checklist.txt"])
    manifest=(root/"manifest.json").read_text(encoding="utf-8");checklist=(root/"checklist.txt").read_text(encoding="utf-8")
    assert "AUDIO_PLATFORM_SELECTION_REQUIRED" in checklist and "revisão manual" in checklist and "Não marcar como publicado" in checklist
    assert all(secret not in manifest.lower() for secret in ["client_secret","access_token","refresh_token"]) and bundle["readinessStatus"]=="BLOCKED" and bundle["remoteRequestExecuted"] is False
