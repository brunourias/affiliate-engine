from io import BytesIO
from pathlib import Path
from PIL import Image
import pytest
from apps.api.app.core.config import settings
from apps.api.app.db.models import Campaign,Creative,CuratorAssessment,CuratorCandidate,CuratorEvidence,MediaAsset
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.static_creative import CarouselCreativeDirector,CreativeFeatureSelector,CreativeFormatRecommender,FeatureIconResolver,StaticCreativeEngine,StaticLayoutDirector

def png(color=(20,120,130),size=(900,900)):
    stream=BytesIO();Image.new("RGBA",size,color+(255,)).save(stream,"PNG");return stream.getvalue()

def setup_static(tmp_path,features=3,assets=1):
    settings.media_root=str(tmp_path)
    with SessionLocal() as db:
        candidate=CuratorCandidate(provider="OTHER",source_type="MANUAL",entity_type="MANUAL",working_title="Parafusadeira doméstica",status="READY_FOR_REVIEW",evidence_status="VERIFIED",evidence_level="DATA_ANALYZED");db.add(candidate);db.flush()
        assessment=CuratorAssessment(candidate_id=candidate.id,assessment_version=1,evidence_status="SUFFICIENT_EVIDENCE",evidence_level="DATA_ANALYZED",trust_gate="PASS",trust_reasons=[],trust_warnings=[],recommendation_score=80,recommendation_coverage_percent=100,recommendation_label="GOOD",opportunity_score=70,opportunity_coverage_percent=100,price_verdict="FAIR_PRICE",editorial_verdict="WORTH_IT",recommendation_pillars={},opportunity_pillars={},evidence_ids_used=[],unknown_fields=[],rationale={});db.add(assessment);db.flush()
        campaign=Campaign(candidate_id=candidate.id,assessment_id=assessment.id,name="Campanha",status="APPROVED",objective="EDUCATION",editorial_verdict_snapshot="WORTH_IT",trust_gate_snapshot="PASS",price_verdict_snapshot="FAIR_PRICE",campaign_priority="HIGH",affiliate_url="https://example.com/product",disclosure_text="Link de afiliado",trust_warnings_snapshot=[],required_disclosures=[],required_warnings=[],forbidden_claims=[]);db.add(campaign);db.flush()
        creative=Creative(campaign_id=campaign.id,name="Card",status="APPROVED",content_type="SHORT_VIDEO",target_channel="GENERIC",angle_type_snapshot="HOME_USE",objective_snapshot="EDUCATION",editorial_verdict_snapshot="WORTH_IT",price_verdict_snapshot="FAIR_PRICE",disclosure_text="Link de afiliado",required_warnings=[],forbidden_claims=[]);db.add(creative);db.flush()
        values=[("USE_CASE","Adequada para pequenos reparos."),("TECHNICAL_SPEC","Mandril de 10 mm."),("LIMITATION","Compare opções para uso contínuo."),("TECHNICAL_SPEC","Duas velocidades verificadas.")]
        for kind,value in values[:features]:db.add(CuratorEvidence(candidate_id=candidate.id,evidence_type=kind,value_text=value,source_kind="MANUAL_OPERATOR",source_reference=f"ref-{kind}",confidence="HIGH",verification_status="VERIFIED"))
        (tmp_path/"assets").mkdir(parents=True,exist_ok=True)
        for index in range(assets):
            path=tmp_path/"assets"/f"{index}.png";path.write_bytes(png((20+index*30,100,130),(900-index*50,900)));classification="HERO_IMAGE" if index==0 else "DETAIL_IMAGE" if index==1 else "ALTERNATE_IMAGE";db.add(MediaAsset(asset_type="PRODUCT_IMAGE",owner_type="CANDIDATE",owner_id=candidate.id,logical_name=path.name,relative_path=f"assets/{path.name}",mime_type="image/png",width=900-index*50,height=900,file_size_bytes=path.stat().st_size,metadata_={"classification":classification},active=True))
        db.commit();return creative.id,candidate.id

def test_static_card_with_one_image_is_valid_png_and_manifest(tmp_path):
    creative_id,_=setup_static(tmp_path)
    with SessionLocal() as db:
        result=StaticCreativeEngine(db).render(creative_id,"STATIC_CARD");path=Path(settings.media_root)/result["files"][0]
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") and result["dimensions"]=={"width":1080,"height":1350}
        assert result["cta"]["text"] and result["sourceAssetId"] and result["qualityChecks"]["STATIC_FEATURE_PROVENANCE"]=="PASS"
        assert (Path(settings.media_root)/result["manifestFile"]).is_file()

def test_hero_selection_feature_limit_and_deterministic_recommender(tmp_path):
    creative_id,_=setup_static(tmp_path,features=4,assets=3)
    with SessionLocal() as db:
        first=StaticCreativeEngine(db).plan(creative_id);second=StaticCreativeEngine(db).plan(creative_id)
        assert first==second and len(first["features"])==3 and first["sourceAssetId"]==first["assetIds"][0]
        assert first["formatRecommendation"]==CreativeFormatRecommender().recommend(StaticCreativeEngine(db).context(creative_id)[4],first["features"])

def test_unverified_feature_is_never_selected_and_manual_unverified_fails():
    evidence=[type("E",(),{"id":"1","evidence_type":"TECHNICAL_SPEC","value_text":"20V","source_kind":"MANUAL_OPERATOR","source_reference":None,"confidence":"HIGH","verification_status":"UNVERIFIED","metadata_":{}})()]
    assert CreativeFeatureSelector().select(evidence)==[]
    assert FeatureIconResolver().resolve("voltage")=="VOLTAGE" and FeatureIconResolver().resolve("unknown")=="GENERIC_FEATURE"

def test_truncated_narrative_evidence_is_not_exposed_as_product_feature():
    evidence=[type("E",(),{"id":"1","evidence_type":"LIMITATION","value_text":"Não indicada para uso profission","source_kind":"MANUAL_OPERATOR","source_reference":"ref","confidence":"HIGH","verification_status":"VERIFIED","metadata_":{}})()]
    assert CreativeFeatureSelector().select(evidence)==[]

def test_layout_director_is_deterministic_and_keeps_feature_count_safe():
    director=StaticLayoutDirector();asset={"aspectRatio":.6};features=[{"verified":True}]*3
    assert director.select(asset,features,"Headline")==director.select(asset,features,"Headline")=="PRODUCT_LEFT_FEATURES_RIGHT"

def test_carousel_has_three_card_story_distributes_assets_and_uses_detail(tmp_path):
    creative_id,_=setup_static(tmp_path,features=3,assets=3)
    with SessionLocal() as db:
        plan=StaticCreativeEngine(db).plan(creative_id,"CAROUSEL");assert [x["role"] for x in plan["cards"]]==["HOOK","DETAIL","CTA"]
        assert len(set(x["sourceAssetId"] for x in plan["cards"]))>=2 and plan["qualityChecks"]["CAROUSEL_STORY_FLOW"]=="PASS"
        assert [x["layout"] for x in plan["cards"]]==["MINIMAL_HERO","DETAIL_CLOSE_UP","CTA_FOCUS"]
        assert plan["cards"][1]["headline"]=="CONFIRA OS DETALHES DO PRODUTO" and plan["cards"][2]["cta"]=="VER PREÇO E DETALHES"
        assert plan["visualLayoutVariation"]=="PASS"
        result=StaticCreativeEngine(db).render(creative_id,"CAROUSEL");assert len(result["files"])==3 and all((Path(settings.media_root)/x).read_bytes().startswith(b"\x89PNG") for x in result["files"])

def test_single_asset_carousel_reports_truthful_warning(tmp_path):
    creative_id,_=setup_static(tmp_path,features=2,assets=1)
    with SessionLocal() as db:
        plan=StaticCreativeEngine(db).plan(creative_id,"CAROUSEL");assert "LOW_CAROUSEL_MEDIA_DIVERSITY" in plan["warnings"] and plan["qualityChecks"]["CAROUSEL_MEDIA_DIVERSITY"]=="WARNING"

def test_static_preview_api_and_existing_approval_flow_remain_available(client,tmp_path):
    creative_id,_=setup_static(tmp_path)
    plan=client.get(f"/api/v1/creatives/{creative_id}/static-plan");assert plan.status_code==200
    made=client.post(f"/api/v1/creatives/{creative_id}/static-preview",json={"format":"STATIC_CARD"});assert made.status_code==201
    filename=Path(made.json()["files"][0]).name;content=client.get(f"/api/v1/creatives/{creative_id}/static-content/static_card/{filename}");assert content.status_code==200 and content.headers["content-type"].startswith("image/png")
