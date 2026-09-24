import json,time
from pathlib import Path
from PIL import Image
from apps.api.app.core.config import settings
from apps.api.app.db.models import CampaignChannel,Creative
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.channel_adaptation import AspectAdaptationPlanner,ChannelAssetAdaptationEngine,ChannelAssetProfileResolver,PROFILES,SafeAreaValidator,VideoAdaptationPlanner
from apps.api.app.services.format_decision import CreativeDistributionPlan
from apps.api.app.services.static_creative import StaticCreativeEngine
from apps.api.tests.test_v1g_static_creatives import setup_static

AVAILABLE={"storage":{"status":"AVAILABLE"},"ffmpeg":{"status":"AVAILABLE"},"ffprobe":{"status":"AVAILABLE"},"tts":{"status":"AVAILABLE"}}

def source_carousel(tmp_path):
    creative_id,_=setup_static(tmp_path,features=0,assets=3)
    with SessionLocal() as db:StaticCreativeEngine(db).render(creative_id,"CAROUSEL")
    return creative_id

def test_profile_resolver_is_deterministic_and_unknown_does_not_invent_dimensions():
    resolver=ChannelAssetProfileResolver();first=resolver.resolve("TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL")
    assert first==resolver.resolve("TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL") and (first["width"],first["height"],first["aspectRatio"])==(720,1280,"9:16")
    unknown=resolver.resolve("TIKTOK","ORGANIC","UNKNOWN","CAROUSEL");assert unknown["compatibility"]=="UNKNOWN" and unknown["width"] is None and unknown["height"] is None

def test_youtube_reels_and_feed_profiles_are_explicit():
    resolver=ChannelAssetProfileResolver()
    assert (resolver.resolve("YOUTUBE_SHORTS","ORGANIC","YOUTUBE_SHORTS","VIDEO_SHORT")["width"],resolver.resolve("YOUTUBE_SHORTS","ORGANIC","YOUTUBE_SHORTS","VIDEO_SHORT")["height"])==(1080,1920)
    assert resolver.resolve("INSTAGRAM","ORGANIC","INSTAGRAM_REELS","VIDEO_SHORT")["aspectRatio"]=="9:16"
    assert resolver.resolve("FACEBOOK","ORGANIC","FACEBOOK_FEED","STATIC_CARD")["aspectRatio"]=="4:5"

def test_aspect_planner_never_stretches_and_video_preserves_timeline_and_captions():
    aspect=AspectAdaptationPlanner().plan(1080,1350,720,1280);assert aspect["strategy"]=="BACKGROUND_EXTEND" and aspect["stretch"] is False
    profile=ChannelAssetProfileResolver().resolve("YOUTUBE_SHORTS","ORGANIC","YOUTUBE_SHORTS","VIDEO_SHORT");video=VideoAdaptationPlanner().plan(profile)
    assert video["timeline"]=="PRESERVE" and video["captionTiming"]=="PRESERVE" and video["voiceSynthesis"] is False

def test_safe_area_detects_overflow_and_cta_violation():
    profile=ChannelAssetProfileResolver().resolve("TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL");validator=SafeAreaValidator()
    assert validator.validate(profile,{"CTA":(50,100,650,1100)})["status"]=="PASS"
    failed=validator.validate(profile,{"CTA":(20,100,700,1250)});assert failed["status"]=="FAIL" and "CTA" in failed["outside"]

def test_plan_preserves_copy_features_provenance_order_and_roles(tmp_path):
    creative_id=source_carousel(tmp_path)
    with SessionLocal() as db:plan=ChannelAssetAdaptationEngine(db).plan(creative_id,"TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL")
    assert [x["role"] for x in plan["cards"]]==["HOOK","DETAIL","CTA"]
    assert [x["headline"] for x in plan["cards"]]==["PRA USO EM CASA?","CONFIRA OS DETALHES DO PRODUTO","ANTES DE ESCOLHER"] and plan["cards"][2]["cta"]=="VER PREÇO E DETALHES"
    assert plan["preservation"]["features"] and plan["preservation"]["provenance"] and plan["preservation"]["cardOrder"]

def test_render_produces_vertical_png_manifest_warnings_and_reuses_current_output(tmp_path):
    creative_id=source_carousel(tmp_path)
    for path in (tmp_path/"assets").glob("*.png"):
        with Image.open(path) as image:image.resize((220,220)).save(path)
    with SessionLocal() as db:
        engine=ChannelAssetAdaptationEngine(db);result=engine.render(creative_id,"TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL")
        root=Path(settings.media_root)/"channel_variants"/creative_id/"TIKTOK_CAROUSEL_PAID_V1";mtimes=[(root/f"card_{x:02}.png").stat().st_mtime_ns for x in range(1,4)];second=engine.render(creative_id,"TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL")
    assert result["adaptationStatus"]==second["adaptationStatus"]=="UP_TO_DATE" and mtimes==[(root/f"card_{x:02}.png").stat().st_mtime_ns for x in range(1,4)]
    assert all(Image.open(root/f"card_{x:02}.png").size==(720,1280) for x in range(1,4));assert "SOURCE_MEDIA_LOW_RESOLUTION" in result["warnings"] and "AUDIO_REQUIRED" in result["warnings"]
    assert result["qualityChecks"]["CHANNEL_SAFE_AREA_VALID"]=="PASS" and (root/"manifest.json").is_file()

def test_fingerprint_is_deterministic_and_profile_change_makes_variant_outdated(tmp_path):
    creative_id=source_carousel(tmp_path)
    with SessionLocal() as db:
        engine=ChannelAssetAdaptationEngine(db);first=engine.render(creative_id,"TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL");same=engine.plan(creative_id,"TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL");assert first["variantFingerprint"]==same["variantFingerprint"] and same["adaptationStatus"]=="UP_TO_DATE"
        old=PROFILES["TIKTOK_CAROUSEL_PAID_V1"]["profileVersion"]
        try:PROFILES["TIKTOK_CAROUSEL_PAID_V1"]["profileVersion"]="2";assert engine.plan(creative_id,"TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL")["adaptationStatus"]=="OUTDATED"
        finally:PROFILES["TIKTOK_CAROUSEL_PAID_V1"]["profileVersion"]=old

def test_distribution_readiness_resolves_variant_but_keeps_audio_block(tmp_path):
    creative_id=source_carousel(tmp_path)
    with SessionLocal() as db:
        creative=db.get(Creative,creative_id);db.add(CampaignChannel(campaign_id=creative.campaign_id,channel="TIKTOK",enabled=True,publication_mode="MANUAL"));db.commit();ChannelAssetAdaptationEngine(db).render(creative_id,"TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL")
        plan=CreativeDistributionPlan(db,lambda:AVAILABLE).create(creative_id,["CAROUSEL"],distribution_mode="PAID_AD");candidate=plan["publicationCandidates"][0];requirements={x["code"]:x["status"] for x in candidate["requirements"]}
    assert requirements["PLATFORM_ASPECT_RATIO_REQUIRED"]=="SATISFIED" and requirements["AUDIO_REQUIRED"]=="MISSING" and candidate["distributionReadiness"]["ready"] is False
    assert "CHANNEL_ASSET_VARIANT_REQUIRED" not in candidate["distributionReadiness"]["warnings"] and "AUDIO_REQUIRED" in candidate["distributionReadiness"]["warnings"]
