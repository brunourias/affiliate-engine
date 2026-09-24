from apps.api.app.db.session import SessionLocal
import pytest
from sqlalchemy import select
from apps.api.app.db.models import CuratorCandidate,CuratorAssessment,Campaign,CampaignExperiment,Creative,CreativeScene,Approval,DecisionLog,MediaJob
from apps.api.app.services import creatives as creative_service
from apps.api.app.services.creative_direction import _copy,quality_checks

def campaign(status="APPROVED",warnings=None,claims=None,campaign_name="Produto seguro",candidate_name="Produto seguro"):
    with SessionLocal() as db:
        c=CuratorCandidate(provider="OTHER",source_type="MANUAL",entity_type="MANUAL",working_title=candidate_name);db.add(c);db.flush();a=CuratorAssessment(candidate_id=c.id,assessment_version=1,evidence_status="SUFFICIENT",evidence_level="PUBLIC_VERIFIED",trust_gate="PASS",trust_reasons=[],trust_warnings=[],recommendation_score=80,recommendation_coverage_percent=100,recommendation_label="GOOD",opportunity_score=70,opportunity_coverage_percent=100,price_verdict="FAIR_PRICE",editorial_verdict="WORTH_IT",recommendation_pillars={},opportunity_pillars={},evidence_ids_used=[],unknown_fields=[],rationale={});db.add(a);db.flush();x=Campaign(candidate_id=c.id,assessment_id=a.id,name=campaign_name,status=status,objective="EDUCATION",editorial_verdict_snapshot="WORTH_IT",trust_gate_snapshot="PASS",recommendation_score_snapshot=80,opportunity_score_snapshot=70,price_verdict_snapshot="FAIR_PRICE",campaign_priority="HIGH",disclosure_text="Conteúdo com link de afiliado.",trust_warnings_snapshot=warnings or [],required_disclosures=[],required_warnings=warnings or [],forbidden_claims=claims or []);db.add(x);db.commit();return x.id
def test_only_approved_campaign_creates_and_snapshots(client):
    for status in ["DRAFT","PENDING_APPROVAL","REJECTED","PAUSED","ARCHIVED"]:assert client.post(f"/api/v1/creatives/from-campaign/{campaign(status)}",json={}).status_code==409
    cid=campaign();r=client.post(f"/api/v1/creatives/from-campaign/{cid}",json={});assert r.status_code==201;body=r.json();assert body["campaignId"]==cid and body["objectiveSnapshot"]=="EDUCATION" and body["priceVerdictSnapshot"]=="FAIR_PRICE"
def test_experiment_trace_and_wrong_campaign_protection(client):
    cid=campaign()
    with SessionLocal() as db:e=CampaignExperiment(campaign_id=cid,hypothesis="Hipótese",hook_strategy="QUESTION",cta_strategy="Compare",target_channel="TIKTOK");db.add(e);db.commit();eid=e.id
    body=client.post(f"/api/v1/creatives/from-experiment/{eid}",json={}).json();assert body["experimentId"]==eid and body["hook"]=="QUESTION" and body["targetChannel"]=="TIKTOK"
def test_template_scenes_compliance_and_readiness(client):
    warning={"code":"LIMIT","message":"Uso doméstico apenas"};cid=campaign(warnings=[warning],claims=["OWN_TEST_CLAIM","BUY_NOW_CTA","PRICE_PROMOTION_CLAIM"]);creative=client.post(f"/api/v1/creatives/from-campaign/{cid}",json={}).json();id=creative["id"];generated=client.post(f"/api/v1/creatives/{id}/generate-template");assert generated.status_code==200;template=generated.json();assert template["hook"] and template["bodyScript"] and template["cta"] and template["estimatedDurationSeconds"]==20;scenes=client.get(f"/api/v1/creatives/{id}/scenes").json();assert len(scenes)==5 and scenes[0]["narrationText"]==template["hook"] and scenes[-1]["narrationText"]==template["cta"];assert client.get(f"/api/v1/creatives/{id}/compliance").json()["requiredWarningCoverage"][0]["status"]=="COVERED"
    client.patch(f"/api/v1/creatives/{id}",json={"bodyScript":"Testamos. Uso doméstico apenas","cta":"Compre agora"});comp=client.get(f"/api/v1/creatives/{id}/compliance").json();assert comp["status"]=="BLOCK" and len(comp["reasons"])>=2
    client.patch(f"/api/v1/creatives/{id}",json={"bodyScript":"Uso doméstico apenas. Conteúdo baseado em evidências.","cta":"Compare os detalhes"});assert client.get(f"/api/v1/creatives/{id}/compliance").json()["status"]=="PASS";assert client.get(f"/api/v1/creatives/{id}/readiness").json()["state"]=="READY_FOR_REVIEW"
def test_scene_edit_delete_and_variant(client):
    id=client.post(f"/api/v1/creatives/from-campaign/{campaign()}",json={}).json()["id"];s=client.post(f"/api/v1/creatives/{id}/scenes",json={"orderIndex":2,"sceneType":"TEXT","purpose":"Contexto"}).json();assert client.patch(f"/api/v1/creatives/{id}/scenes/{s['id']}",json={"orderIndex":1}).json()["orderIndex"]==1;v=client.post(f"/api/v1/creatives/{id}/variant",json={"variantLabel":"A2"}).json();assert v["parentCreativeId"]==id and v["variantGroup"];assert client.delete(f"/api/v1/creatives/{id}/scenes/{s['id']}").status_code==204
def test_approval_sync_and_immutability(client):
    id=client.post(f"/api/v1/creatives/from-campaign/{campaign()}",json={}).json()["id"];client.post(f"/api/v1/creatives/{id}/generate-template");client.patch(f"/api/v1/creatives/{id}",json={"bodyScript":"Texto baseado em evidências","cta":"Compare"});approval=client.post(f"/api/v1/creatives/{id}/submit-for-review").json();assert approval["type"]=="CREATIVE";assert client.patch(f"/api/v1/creatives/{id}",json={"hook":"mudar"}).status_code==409;client.post(f"/api/v1/approvals/{approval['id']}/approve",json={});assert client.get(f"/api/v1/creatives/{id}").json()["status"]=="APPROVED"
def test_rejected_is_editable(client):
    id=client.post(f"/api/v1/creatives/from-campaign/{campaign()}",json={}).json()["id"];client.post(f"/api/v1/creatives/{id}/generate-template");client.patch(f"/api/v1/creatives/{id}",json={"bodyScript":"Texto","cta":"Compare"});approval=client.post(f"/api/v1/creatives/{id}/submit-for-review").json();client.post(f"/api/v1/approvals/{approval['id']}/reject",json={});assert client.patch(f"/api/v1/creatives/{id}",json={"hook":"Novo hook"}).status_code==200

def approved_creative(client):
    creative_id=client.post(f"/api/v1/creatives/from-campaign/{campaign()}",json={}).json()["id"];client.post(f"/api/v1/creatives/{creative_id}/generate-template");approval=client.post(f"/api/v1/creatives/{creative_id}/submit-for-review").json();client.post(f"/api/v1/approvals/{approval['id']}/approve",json={});return creative_id

def test_duplicate_approved_creative_copies_editorial_content_and_scenes_only(client):
    source_id=approved_creative(client);source=client.get(f"/api/v1/creatives/{source_id}").json();source_scenes=client.get(f"/api/v1/creatives/{source_id}/scenes").json()
    with SessionLocal() as db:db.add(MediaJob(creative_id=source_id,render_type="PREVIEW",status="COMPLETED",width=540,height=960,fps=30,video_codec="h264",audio_codec="aac",progress_percent=100));db.commit()
    response=client.post(f"/api/v1/creatives/{source_id}/duplicate");assert response.status_code==201;copy=response.json();copy_scenes=client.get(f"/api/v1/creatives/{copy['id']}/scenes").json()
    assert copy["id"]!=source_id and copy["status"]=="DRAFT" and copy["parentCreativeId"]==source_id and copy["approvedAt"] is None and copy["rejectedAt"] is None
    for field in ("title","contentPremise","hook","bodyScript","cta","disclosureText","requiredWarnings","forbiddenClaims","angleTypeSnapshot","generationMode"):assert copy[field]==source[field]
    assert len(copy_scenes)==len(source_scenes) and {x["id"] for x in copy_scenes}.isdisjoint({x["id"] for x in source_scenes})
    assert [(x["orderIndex"],x["sceneType"],x["speaker"],x["avatarState"],x["narrationText"],x["onScreenText"]) for x in copy_scenes]==[(x["orderIndex"],x["sceneType"],x["speaker"],x["avatarState"],x["narrationText"],x["onScreenText"]) for x in source_scenes]
    assert client.patch(f"/api/v1/creatives/{copy['id']}",json={"hook":"Hook editável"}).status_code==200
    with SessionLocal() as db:
        assert db.get(Creative,source_id).status=="APPROVED" and db.scalar(select(MediaJob).where(MediaJob.creative_id==copy["id"])) is None and db.scalar(select(Approval).where(Approval.entity_id==copy["id"])) is None
        decision=db.scalar(select(DecisionLog).where(DecisionLog.entity_id==copy["id"],DecisionLog.action=="CREATIVE_DUPLICATED"));assert decision.metadata_["sourceCreativeId"]==source_id and decision.metadata_["newCreativeId"]==copy["id"]

def test_duplicate_rolls_back_creative_and_scenes_when_copy_fails(client,monkeypatch):
    source_id=approved_creative(client);monkeypatch.setattr(creative_service,"log_decision",lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError("falha simulada")))
    with pytest.raises(RuntimeError):client.post(f"/api/v1/creatives/{source_id}/duplicate")
    with SessionLocal() as db:assert db.scalars(select(Creative).where(Creative.parent_creative_id==source_id)).all()==[]


def test_tiktok_first_variant_is_deterministic_short_and_keeps_source_immutable(client):
    source_id=approved_creative(client);before=client.get(f"/api/v1/creatives/{source_id}").json();response=client.post(f"/api/v1/creatives/{source_id}/tiktok-variant");assert response.status_code==201;created=response.json();scenes=client.get(f"/api/v1/creatives/{created['id']}/scenes").json();direction=client.get(f"/api/v1/creatives/{created['id']}/creative-direction").json()
    assert created["status"]=="DRAFT" and created["targetChannel"]=="TIKTOK" and created["generationMode"]=="TIKTOK_FIRST" and created["parentCreativeId"]==source_id
    assert client.get(f"/api/v1/creatives/{source_id}").json()==before and scenes[0]["purpose"]=="HOOK" and scenes[-1]["purpose"]=="CTA"
    assert [x["orderIndex"] for x in scenes]==list(range(len(scenes))) and all((x["durationSeconds"] or 0)<=3.5 for x in scenes)
    assert direction["hookText"] and direction["ctaText"] and direction["storyboard"][0]["productFocus"] is True and set(direction["qualityChecks"].values())=={"PASS"}


def test_tiktok_direction_uses_human_product_and_home_use_persona_without_inventing_facts(client):
    cid=campaign(campaign_name="Campanha do candidato",candidate_name="TESTE V1-D — Parafusadeira doméstica");draft=client.post(f"/api/v1/creatives/from-campaign/{cid}",json={}).json();direction=client.get(f"/api/v1/creatives/{draft['id']}/creative-direction").json()
    assert direction["creativeAngle"]=="HOME_USE" and direction["persona"]=="CAROL" and direction["hookType"]=="QUESTION"
    assert "parafusadeira" in direction["hookText"].casefold() and "Parafusadeira doméstica" not in direction["hookText"] and "Campanha do candidato" not in direction["hookText"]


def test_tiktok_variant_requires_approved_source_and_limits_variations(client):
    draft=client.post(f"/api/v1/creatives/from-campaign/{campaign()}",json={}).json();assert client.post(f"/api/v1/creatives/{draft['id']}/tiktok-variant").status_code==409
    source_id=approved_creative(client)
    for _ in range(3):assert client.post(f"/api/v1/creatives/{source_id}/tiktok-variant").status_code==201
    assert client.post(f"/api/v1/creatives/{source_id}/tiktok-variant").status_code==409


def test_tiktok_quality_flags_missing_cta_and_long_scene():
    row=type("CreativeStub",(),{"hook":"Hook"})();storyboard=[{"purpose":"HOOK","scriptSegment":"Hook curto","recommendedDuration":2,"productFocus":True},{"purpose":"VALUE","scriptSegment":" ".join(["texto"]*20),"recommendedDuration":4,"productFocus":True}]
    checks=quality_checks(row,storyboard);assert checks["ctaClarity"]=="FAIL" and checks["scenePacing"]=="WARNING" and checks["productVisibility"]=="PASS"


def test_tiktok_spoken_copy_avoids_catalog_name_varies_rhythm_and_supports_micro_scenes(client):
    cid=campaign(campaign_name="Campanha do candidato",candidate_name="TESTE V1-D — Parafusadeira doméstica");source=client.post(f"/api/v1/creatives/from-campaign/{cid}",json={}).json();client.post(f"/api/v1/creatives/{source['id']}/generate-template");approval=client.post(f"/api/v1/creatives/{source['id']}/submit-for-review").json();client.post(f"/api/v1/approvals/{approval['id']}/approve",json={});created=client.post(f"/api/v1/creatives/{source['id']}/tiktok-variant").json();direction=client.get(f"/api/v1/creatives/{created['id']}/creative-direction").json();spoken=" ".join(x["scriptSegment"] for x in direction["storyboard"])
    assert "Parafusadeira doméstica" not in spoken and "eu testei" not in spoken.casefold() and "eu comprei" not in spoken.casefold()
    assert len(direction["hookText"].split())<=12 and "Dá uma olhada" in direction["ctaText"]
    assert len({x["recommendedDuration"] for x in direction["storyboard"]})>1
    problem=next(x for x in direction["storyboard"] if x["purpose"]=="PROBLEM");assert len(problem["visualUnits"])==2 and [x["visualUnitIndex"] for x in problem["visualUnits"]]==[0,1] and all(x["speechSegmentId"]==problem["speechSegmentId"] for x in problem["visualUnits"])
    assert set(direction["qualityChecks"].values())=={"PASS"}


def test_persona_changes_style_without_changing_product_facts():
    base={"subject":"Produto interno","creativeAngle":"HOME_USE","ctaType":"SEE_IF_IT_FITS"};carol=_copy({**base,"persona":"CAROL"})[2];bruno=_copy({**base,"persona":"BRUNO"})[2]
    assert carol[0]["scriptSegment"]!=bruno[0]["scriptSegment"] and [x["purpose"] for x in carol]==[x["purpose"] for x in bruno]
    assert "Produto interno" not in " ".join(x["scriptSegment"] for x in carol+bruno)


def test_quality_checks_detect_artificial_catalog_language_and_uniform_rhythm():
    row=type("CreativeStub",(),{"hook":"Hook","title":"Parafusadeira doméstica: vale a pena?"})();storyboard=[{"purpose":"HOOK","scriptSegment":"Parafusadeira doméstica pode ser adequada para utilização doméstica.","recommendedDuration":3,"productFocus":True,"visualIntent":"PRODUCT_HERO","visualUnits":[{"visualIntent":"PRODUCT_HERO","estimatedDuration":3}]},{"purpose":"CTA","scriptSegment":"Veja se faz sentido para o seu uso.","recommendedDuration":3,"productFocus":True,"visualIntent":"CTA","visualUnits":[{"visualIntent":"CTA","estimatedDuration":3}]}]
    checks=quality_checks(row,storyboard);assert checks["naturalSpeech"]=="WARNING" and checks["catalogLanguage"]=="FAIL" and checks["ctaNaturalness"]=="WARNING" and checks["rhythmVariation"]=="WARNING"


def test_template_prefers_human_candidate_name_and_preserves_internal_enums(client):
    cid=campaign(campaign_name="Campanha do candidato",candidate_name="TESTE V1-D — Parafusadeira doméstica",claims=["BEST_ON_MARKET_UNSUPPORTED"])
    created=client.post(f"/api/v1/creatives/from-campaign/{cid}",json={}).json();creative_id=created["id"];generated=client.post(f"/api/v1/creatives/{creative_id}/generate-template").json()
    assert "Parafusadeira doméstica" in generated["hook"] and "Campanha do candidato" not in generated["hook"] and "TESTE V1-D" not in generated["hook"]
    assert generated["title"]=="Parafusadeira doméstica: vale a pena?" and generated["contentPremise"] and generated["forbiddenClaims"]==["BEST_ON_MARKET_UNSUPPORTED"]
    assert "Estrutura inicial" not in generated["bodyScript"]
    scenes=client.get(f"/api/v1/creatives/{creative_id}/scenes").json();assert scenes[0]["narrationText"]==generated["hook"] and scenes[-1]["narrationText"]==generated["cta"]

def test_template_overwrite_replaces_old_scenes_and_updates_fields(client):
    cid=campaign(campaign_name="Campanha do candidato",candidate_name="TESTE V1-D — Parafusadeira doméstica")
    creative=client.post(f"/api/v1/creatives/from-campaign/{cid}",json={}).json();creative_id=creative["id"]
    old=client.post(f"/api/v1/creatives/{creative_id}/scenes",json={"orderIndex":0,"sceneType":"TEXT","purpose":"OLD","narrationText":"Cena antiga"}).json()
    assert client.post(f"/api/v1/creatives/{creative_id}/generate-template",json={"overwrite":False}).status_code==409
    generated=client.post(f"/api/v1/creatives/{creative_id}/generate-template",json={"overwrite":True}).json();scenes=client.get(f"/api/v1/creatives/{creative_id}/scenes").json()
    assert len(scenes)==5 and old["id"] not in {scene["id"] for scene in scenes}
    assert generated["title"]=="Parafusadeira doméstica: vale a pena?" and generated["hook"] and generated["bodyScript"] and generated["cta"]
    assert "Campanha do candidato" not in generated["hook"] and "Estrutura inicial" not in generated["bodyScript"]
    assert scenes[0]["narrationText"]==generated["hook"] and scenes[-1]["narrationText"]==generated["cta"]

def test_template_overwrite_is_atomic_and_requires_editable_creative(client,monkeypatch):
    creative_id=client.post(f"/api/v1/creatives/from-campaign/{campaign()}",json={}).json()["id"]
    old=client.post(f"/api/v1/creatives/{creative_id}/scenes",json={"orderIndex":0,"sceneType":"TEXT","purpose":"OLD","narrationText":"Cena preservada"}).json()
    monkeypatch.setattr(creative_service,"log_decision",lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError("falha simulada")))
    with pytest.raises(RuntimeError):client.post(f"/api/v1/creatives/{creative_id}/generate-template",json={"overwrite":True})
    with SessionLocal() as db:
        scenes=db.scalars(select(CreativeScene).where(CreativeScene.creative_id==creative_id)).all();assert len(scenes)==1 and scenes[0].id==old["id"] and scenes[0].narration_text=="Cena preservada"
    monkeypatch.undo();client.delete(f"/api/v1/creatives/{creative_id}/scenes/{old['id']}");client.post(f"/api/v1/creatives/{creative_id}/generate-template",json={});approval=client.post(f"/api/v1/creatives/{creative_id}/submit-for-review",json={}).json()
    assert approval["status"]=="PENDING" and client.post(f"/api/v1/creatives/{creative_id}/generate-template",json={"overwrite":True}).status_code==409

@pytest.mark.parametrize("text",["melhor do mercado","Esta é a melhor parafusadeira do mercado.","O MELHOR PRODUTO DO MERCADO"])
def test_best_on_market_variations_block_in_hook(client,text):
    creative_id=client.post(f"/api/v1/creatives/from-campaign/{campaign(claims=['BEST_ON_MARKET_UNSUPPORTED'])}",json={}).json()["id"]
    client.patch(f"/api/v1/creatives/{creative_id}",json={"hook":text});result=client.get(f"/api/v1/creatives/{creative_id}/compliance").json()
    assert result["status"]=="BLOCK" and result["reasons"]==[{"code":"BEST_ON_MARKET_UNSUPPORTED","message":"Alegação de 'melhor do mercado' sem evidência suficiente."}]

@pytest.mark.parametrize("field",["title","hook","bodyScript","cta"])
def test_compliance_checks_every_creative_text_field(client,field):
    creative_id=client.post(f"/api/v1/creatives/from-campaign/{campaign(claims=['BEST_ON_MARKET_UNSUPPORTED'])}",json={}).json()["id"]
    client.patch(f"/api/v1/creatives/{creative_id}",json={field:"Esta é a melhor parafusadeira do mercado."});assert client.get(f"/api/v1/creatives/{creative_id}/compliance").json()["status"]=="BLOCK"

@pytest.mark.parametrize("field",["narrationText","onScreenText"])
def test_compliance_checks_scene_text_and_allows_safe_content(client,field):
    creative_id=client.post(f"/api/v1/creatives/from-campaign/{campaign(claims=['BEST_ON_MARKET_UNSUPPORTED'])}",json={}).json()["id"]
    safe=client.get(f"/api/v1/creatives/{creative_id}/compliance").json();assert safe["status"]=="PASS"
    body={"orderIndex":0,"sceneType":"TEXT","purpose":"REVIEW",field:"A MELHOR PARAFUSADEIRA DO MERCADO"};client.post(f"/api/v1/creatives/{creative_id}/scenes",json=body);assert client.get(f"/api/v1/creatives/{creative_id}/compliance").json()["status"]=="BLOCK"

@pytest.mark.parametrize("claim,text",[("LOWEST_PRICE_UNVERIFIED","Este é o menor preço."),("NO_DEFECTS_CLAIM","Produto sem nenhum defeito."),("ONE_HUNDRED_PERCENT_RECOMMENDED","É 100% recomendado."),("OWN_TEST_CLAIM","Nós testamos este produto."),("PRICE_PROMOTION_CLAIM","Uma oferta incrível."),("BUY_NOW_CTA","Compre agora.")])
def test_other_forbidden_claim_patterns_remain_narrow_and_effective(client,claim,text):
    creative_id=client.post(f"/api/v1/creatives/from-campaign/{campaign(claims=[claim])}",json={}).json()["id"]
    client.patch(f"/api/v1/creatives/{creative_id}",json={"bodyScript":text});assert client.get(f"/api/v1/creatives/{creative_id}/compliance").json()["status"]=="BLOCK"
