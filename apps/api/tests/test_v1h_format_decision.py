import json
from pathlib import Path
from apps.api.app.core.config import settings
from apps.api.app.db.models import CampaignChannel,Creative,CreativeScene,DecisionLog,MediaAsset
from sqlalchemy import select
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.format_decision import CreativeDistributionPlan,CreativeFormatDecisionEngine
from apps.api.tests.test_v1g_static_creatives import png,setup_static

AVAILABLE={"storage":{"status":"AVAILABLE"},"ffmpeg":{"status":"AVAILABLE"},"ffprobe":{"status":"AVAILABLE"},"tts":{"status":"AVAILABLE"}}
UNAVAILABLE={**AVAILABLE,"tts":{"status":"NOT_CONFIGURED"}}

def by_format(result,format):return next(x for x in result["recommendations"] if x["format"]==format)

def test_one_good_image_prefers_static_and_does_not_invent_features(tmp_path):
    creative_id,_=setup_static(tmp_path,features=0,assets=1)
    with SessionLocal() as db:
        result=CreativeFormatDecisionEngine(db,lambda:AVAILABLE).evaluate(creative_id)
        assert by_format(result,"STATIC_CARD")["priority"]=="HIGH"
        assert by_format(result,"CAROUSEL")["priority"]=="LOW"
        assert "LOW_VERIFIED_FEATURE_COUNT" in [x["code"] for x in by_format(result,"CAROUSEL")["reasons"]]

def test_multiple_images_detail_and_features_favor_carousel(tmp_path):
    creative_id,_=setup_static(tmp_path,features=4,assets=3)
    with SessionLocal() as db:
        result=CreativeFormatDecisionEngine(db,lambda:AVAILABLE).evaluate(creative_id);carousel=by_format(result,"CAROUSEL")
        assert carousel["priority"]=="HIGH" and carousel["readiness"]=="READY"
        assert {"DETAIL_IMAGE_AVAILABLE","FEATURE_RICH_PRODUCT"}<={x["code"] for x in carousel["reasons"]}

def test_native_video_and_narrative_favor_video_without_changing_other_readiness(tmp_path):
    creative_id,candidate_id=setup_static(tmp_path,features=2,assets=2)
    video=tmp_path/"assets"/"native.mp4";video.write_bytes(b"video")
    with SessionLocal() as db:
        creative=db.get(Creative,creative_id);creative.body_script="Uma narrativa de comparação com contexto e objeção. "*10
        db.add(CreativeScene(creative_id=creative_id,order_index=0,scene_type="HOOK",speaker="CAROL",purpose="Contexto",narration_text="Uma explicação narrada.",required_warning_codes=[]))
        db.add(MediaAsset(asset_type="PRODUCT_VIDEO",owner_type="CANDIDATE",owner_id=candidate_id,logical_name="native.mp4",relative_path="assets/native.mp4",mime_type="video/mp4",width=1080,height=1920,file_size_bytes=5,metadata_={"classification":"VIDEO_CLIP"},active=True));db.commit()
        result=CreativeFormatDecisionEngine(db,lambda:UNAVAILABLE).evaluate(creative_id);video_result=by_format(result,"VIDEO_SHORT")
        assert video_result["priority"]=="HIGH" and video_result["readiness"]=="NOT_READY"
        assert by_format(result,"STATIC_CARD")["readiness"]=="READY"

def test_fingerprint_is_deterministic_and_asset_change_invalidates_it(tmp_path):
    creative_id,candidate_id=setup_static(tmp_path,assets=1)
    with SessionLocal() as db:
        engine=CreativeFormatDecisionEngine(db,lambda:AVAILABLE);first=engine.input_fingerprint(creative_id,"STATIC_CARD")
        assert first==engine.input_fingerprint(creative_id,"STATIC_CARD")
        extra=tmp_path/"assets"/"new.png";extra.write_bytes(png((200,30,40)))
        db.add(MediaAsset(asset_type="PRODUCT_IMAGE",owner_type="CANDIDATE",owner_id=candidate_id,logical_name="new.png",relative_path="assets/new.png",mime_type="image/png",width=900,height=900,file_size_bytes=extra.stat().st_size,metadata_={"classification":"DETAIL_IMAGE"},active=True));db.commit()
        assert first!=engine.input_fingerprint(creative_id,"STATIC_CARD")

def test_output_fingerprint_distinguishes_current_and_outdated(tmp_path):
    creative_id,_=setup_static(tmp_path,assets=1)
    with SessionLocal() as db:
        engine=CreativeFormatDecisionEngine(db,lambda:AVAILABLE);fingerprint=engine.input_fingerprint(creative_id,"STATIC_CARD");root=Path(settings.media_root)/"static"/creative_id/"static_card";root.mkdir(parents=True);(root/"manifest.json").write_text(json.dumps({"inputFingerprint":fingerprint}),encoding="utf-8")
        assert by_format(engine.evaluate(creative_id,AVAILABLE),"STATIC_CARD")["outputStatus"]=="UP_TO_DATE"
        creative=db.get(Creative,creative_id);creative.title="Nova versão";db.commit()
        assert by_format(engine.evaluate(creative_id,AVAILABLE),"STATIC_CARD")["outputStatus"]=="OUTDATED"

def test_distribution_plan_is_multiformat_user_controlled_and_never_generates(tmp_path):
    creative_id,_=setup_static(tmp_path,assets=3)
    with SessionLocal() as db:
        service=CreativeDistributionPlan(db,lambda:AVAILABLE);suggested=service.create(creative_id)
        assert len(suggested["recommendedSelection"])>=2 and suggested["automaticGeneration"] is False and suggested["publicationEnabled"] is False
        selected=service.create(creative_id,["STATIC_CARD"],write_log=True);assert selected["selectedFormats"]==["STATIC_CARD"] and len(selected["publicationCandidates"])==1
        candidate=selected["publicationCandidates"][0];assert candidate["distributionReadiness"]["ready"] is False and candidate["distributionReadiness"]["disclosureRequired"]=="UNKNOWN"
        assert selected["experimentId"]==suggested["experimentId"]
        assert "impressions" in selected["metricsFoundation"]["fields"] and selected["metricsFoundation"]["collectionEnabled"] is False
        actions=set(db.scalars(select(DecisionLog.action).where(DecisionLog.entity_id==creative_id)).all());assert {"DISTRIBUTION_PLAN_CREATED","PUBLICATION_CANDIDATE_CREATED"}<=actions

def test_tiktok_paid_carousel_has_explicit_limitations_without_changing_priority(tmp_path):
    creative_id,_=setup_static(tmp_path,features=0,assets=3)
    with SessionLocal() as db:
        creative=db.get(Creative,creative_id);db.add(CampaignChannel(campaign_id=creative.campaign_id,channel="TIKTOK",enabled=True,publication_mode="MANUAL"));db.add(CreativeScene(creative_id=creative_id,order_index=0,scene_type="HOOK",speaker="CAROL",purpose="Hook",narration_text="Narração.",required_warning_codes=[]));db.commit()
        root=Path(settings.media_root)/"static"/creative_id/"carousel";root.mkdir(parents=True);(root/"manifest.json").write_text(json.dumps({"cards":[{"file":"card_01.png"},{"file":"card_02.png"},{"file":"card_03.png"}]}),encoding="utf-8")
        plan=CreativeDistributionPlan(db,lambda:AVAILABLE).create(creative_id,["STATIC_CARD","CAROUSEL","VIDEO_SHORT"],distribution_mode="PAID_AD")
        carousel=next(x for x in plan["publicationCandidates"] if x["format"]=="CAROUSEL");priority=next(x for x in plan["recommendations"] if x["format"]=="CAROUSEL")["priority"]
        assert priority=="HIGH" and carousel["compatibility"]=="SUPPORTED_WITH_LIMITATIONS" and carousel["distributionReadiness"]["ready"] is False
        requirements={x["code"]:x["status"] for x in carousel["requirements"]};assert requirements=={"MIN_IMAGE_COUNT":"SATISFIED","SHARED_DESTINATION_URL":"SATISFIED","AUDIO_REQUIRED":"MISSING","PLATFORM_ASPECT_RATIO_REQUIRED":"MISSING"}
        assert {"AUDIO_REQUIRED","PLATFORM_ASPECT_RATIO_REQUIRED","CHANNEL_ASSET_VARIANT_REQUIRED"}<=set(carousel["distributionReadiness"]["warnings"])
        unavailable=CreativeDistributionPlan(db,lambda:UNAVAILABLE).create(creative_id,["VIDEO_SHORT"],distribution_mode="PAID_AD")["publicationCandidates"][0]
        assert unavailable["distributionReadiness"]["creativeReadiness"]=="NOT_READY" and "TECHNICAL_DEPENDENCY_UNAVAILABLE" in unavailable["distributionReadiness"]["warnings"]

def test_tiktok_organic_unconfigured_formats_remain_unknown_and_matrix_is_deterministic(tmp_path):
    creative_id,_=setup_static(tmp_path,assets=2)
    with SessionLocal() as db:
        creative=db.get(Creative,creative_id);db.add(CampaignChannel(campaign_id=creative.campaign_id,channel="TIKTOK",enabled=True,publication_mode="MANUAL"));db.commit();service=CreativeDistributionPlan(db,lambda:AVAILABLE)
        first=service.create(creative_id,["CAROUSEL"],distribution_mode="ORGANIC");second=service.create(creative_id,["CAROUSEL"],distribution_mode="ORGANIC")
        assert first==second and first["publicationCandidates"][0]["compatibility"]=="UNKNOWN"
