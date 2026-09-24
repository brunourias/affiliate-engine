from pathlib import Path
from apps.api.app.db.models import CampaignChannel,Creative,MediaAsset
from apps.api.app.db.session import SessionLocal
from apps.api.app.core.config import settings
from apps.api.app.services.channel_adaptation import ChannelAssetAdaptationEngine
from apps.api.app.services.publication_readiness import AudioLicenseValidator,AudioRequirementResolver,DisclosureRequirementResolver,PublicationReadinessEngine
from apps.api.tests.test_v1i_channel_adaptation import source_carousel

def ready_creative(tmp_path):
    creative_id=source_carousel(tmp_path)
    with SessionLocal() as db:
        creative=db.get(Creative,creative_id);db.add(CampaignChannel(campaign_id=creative.campaign_id,channel="TIKTOK",enabled=True,publication_mode="MANUAL"));db.commit();ChannelAssetAdaptationEngine(db).render(creative_id,"TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL")
    return creative_id

def test_tiktok_carousel_audio_profile_is_verified_not_invented():
    rule=AudioRequirementResolver().resolve("TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL");assert rule["required"] and rule["minDurationSeconds"]==2 and rule["acceptedFormats"]==["MP3"] and rule["source"]=="TIKTOK_ADS_DOCUMENTATION"
    assert AudioRequirementResolver().resolve("TIKTOK","ORGANIC","UNKNOWN","CAROUSEL")["status"]=="UNKNOWN"

def test_current_state_blocks_audio_and_unknown_disclosure(tmp_path):
    creative_id=ready_creative(tmp_path)
    with SessionLocal() as db:result=PublicationReadinessEngine(db).evaluate(creative_id)
    codes={x["code"] for x in result["blockers"]};assert result["readinessStatus"]=="BLOCKED" and {"AUDIO_REQUIRED","DISCLOSURE_REQUIREMENT_UNKNOWN"}<=codes and result["publicationEnabled"] is False

def test_platform_audio_is_satisfiable_but_manual_and_disclosure_still_blocks(tmp_path):
    creative_id=ready_creative(tmp_path);audio={"mode":"PLATFORM","sourceType":"TIKTOK_CML","selectionRequiredAtPublication":True}
    with SessionLocal() as db:result=PublicationReadinessEngine(db).evaluate(creative_id,audio_plan=audio)
    assert result["audioPlan"]["status"]=="AUDIO_PLATFORM_SELECTION_REQUIRED" and "AUDIO_REQUIRED" not in {x["code"] for x in result["blockers"]}
    assert "AUDIO_PLATFORM_SELECTION_REQUIRED" in {x["code"] for x in result["warnings"]} and result["manualReviewRequired"] and result["readinessStatus"]=="BLOCKED"

def test_valid_local_mp3_satisfies_but_short_invalid_and_licenses_block(tmp_path):
    creative_id=ready_creative(tmp_path)
    with SessionLocal() as db:
        asset=MediaAsset(asset_type="AUDIO_MUSIC",owner_type="CREATIVE",owner_id=creative_id,logical_name="music.mp3",relative_path=f"audio/{creative_id}.mp3",mime_type="audio/mpeg",file_size_bytes=10,metadata_={"durationSeconds":3,"format":"MP3","sourceType":"LOCAL_FILE","licenseStatus":"VERIFIED","licenseReference":"operator-record","commercialUseAllowed":True});db.add(asset);db.commit();db.refresh(asset);engine=PublicationReadinessEngine(db)
        valid=engine.evaluate(creative_id,audio_plan={"mode":"LOCAL","mediaAssetId":asset.id});asset.metadata_={**asset.metadata_,"durationSeconds":1};db.commit();short=engine.evaluate(creative_id,audio_plan={"mode":"LOCAL","mediaAssetId":asset.id});asset.metadata_={**asset.metadata_,"durationSeconds":3,"licenseStatus":"NOT_ALLOWED"};db.commit();denied=engine.evaluate(creative_id,audio_plan={"mode":"LOCAL","mediaAssetId":asset.id})
    assert valid["audioPlan"]["status"]=="AUDIO_PRESENT" and short["audioPlan"]["status"]==denied["audioPlan"]["status"]=="AUDIO_INVALID"
    assert AudioLicenseValidator().validate({})=="UNKNOWN" and AudioLicenseValidator().validate({"licenseStatus":"NOT_ALLOWED"})=="NOT_ALLOWED"

def test_disclosure_unknown_required_missing_present_and_platform_tool():
    resolver=DisclosureRequirementResolver();unknown=resolver.resolve("TIKTOK","PAID_AD","AFFILIATE_LINK","CAROUSEL");required=resolver.resolve("TIKTOK","PAID_AD","AFFILIATE_LINK","CAROUSEL",{"requirementStatus":"REQUIRED"})
    assert unknown["requirementStatus"]=="UNKNOWN" and unknown["manualReviewRequired"] is True and required["required"] is True
    assert PublicationReadinessEngine._disclosure_status(required,{"status":"MISSING"})["status"]=="MISSING"
    assert PublicationReadinessEngine._disclosure_status(required,{"status":"PRESENT","text":"Texto manual"})["status"]=="PRESENT"
    required["platformToolRequired"]=True;assert PublicationReadinessEngine._disclosure_status(required,{})["status"]=="PLATFORM_TOOL_REQUIRED"

def test_approval_urls_tracking_and_fingerprint_changes(tmp_path):
    creative_id=ready_creative(tmp_path);platform={"mode":"PLATFORM","sourceType":"TIKTOK_CML","selectionRequiredAtPublication":True};disclosure={"requirementStatus":"UNKNOWN","status":"PRESENT","text":"Texto manual","placement":"CAPTION"}
    with SessionLocal() as db:
        engine=PublicationReadinessEngine(db);first=engine.evaluate(creative_id,audio_plan=platform,disclosure_plan=disclosure,tracking={"utmSource":"tiktok"});same=engine.evaluate(creative_id,audio_plan=platform,disclosure_plan=disclosure,tracking={"utmSource":"tiktok"});changed=engine.evaluate(creative_id,audio_plan=platform,disclosure_plan={**disclosure,"text":"Outro texto"},tracking={"utmSource":"tiktok"});creative=db.get(Creative,creative_id);creative.status="DRAFT";db.commit();draft=engine.evaluate(creative_id,audio_plan=platform,disclosure_plan=disclosure)
    assert first["packageFingerprint"]==same["packageFingerprint"]!=changed["packageFingerprint"] and first["affiliateUrl"]
    assert first["trackingPlan"]["effectiveDestinationUrl"].count("utm_source=")==1 and "APPROVAL_REQUIRED" in {x["code"] for x in draft["blockers"]}
    assert PublicationReadinessEngine.valid_url("https://example.com") and not PublicationReadinessEngine.valid_url("javascript:bad")

def test_prepare_writes_manifest_logs_without_publish_and_detects_outdated(tmp_path):
    creative_id=ready_creative(tmp_path);audio={"mode":"PLATFORM","sourceType":"TIKTOK_CML","selectionRequiredAtPublication":True};disclosure={"requirementStatus":"UNKNOWN","status":"PRESENT","text":"Texto A","placement":"CAPTION"}
    with SessionLocal() as db:
        engine=PublicationReadinessEngine(db);first=engine.prepare(creative_id,audio_plan=audio,disclosure_plan=disclosure);second=engine.prepare(creative_id,audio_plan=audio,disclosure_plan={**disclosure,"text":"Texto B"})
    assert first["packageStatus"]=="BLOCKED" and second["packageStatus"]=="OUTDATED" and second["publicationEnabled"] is False
    assert (Path(settings.media_root)/"publication_packages").exists() and any("publique manualmente" in x for x in second["manualPublicationInstructions"])
