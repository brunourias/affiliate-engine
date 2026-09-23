import subprocess
import pytest
from apps.api.app.core.config import settings
from sqlalchemy import select
from apps.api.app.db.models import Campaign, Creative, CreativeScene, CuratorAssessment, CuratorCandidate, DecisionLog, MediaAsset, MediaJob
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.media import binary_diagnostic,piper_probe
from apps.api.app.services.voice_engine import CHATTERBOX_IMPORT_PROBE,chatterbox_probe
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.media_pipeline import AssetResolver,FakeMediaValidator,FakeSceneRenderer,FakeTimelineComposer,FakeVoiceRenderer,build_specs,recover_interrupted,run_pipeline
from apps.api.app.services.brand_assets import Box,fit_asset,layout_boxes,safe_areas

def creative(status="APPROVED"):
    with SessionLocal() as db:
        candidate=CuratorCandidate(provider="OTHER",source_type="MANUAL",entity_type="MANUAL");db.add(candidate);db.flush();assessment=CuratorAssessment(candidate_id=candidate.id,assessment_version=1,evidence_status="SUFFICIENT_EVIDENCE",evidence_level="DATA_ANALYZED",trust_gate="PASS",trust_reasons=[],trust_warnings=[],recommendation_score=80,recommendation_coverage_percent=100,recommendation_label="GOOD",opportunity_score=70,opportunity_coverage_percent=100,price_verdict="FAIR_PRICE",editorial_verdict="WORTH_IT",recommendation_pillars={},opportunity_pillars={},evidence_ids_used=[],unknown_fields=[],rationale={});db.add(assessment);db.flush();campaign=Campaign(candidate_id=candidate.id,assessment_id=assessment.id,name="Produto",status="APPROVED",objective="EDUCATION",editorial_verdict_snapshot="WORTH_IT",trust_gate_snapshot="PASS",price_verdict_snapshot="FAIR_PRICE",campaign_priority="HIGH",disclosure_text="Afiliado",trust_warnings_snapshot=[],required_disclosures=[],required_warnings=[],forbidden_claims=[]);db.add(campaign);db.flush()
        row=Creative(campaign_id=campaign.id,name="Criativo",status=status,content_type="SHORT_VIDEO",target_channel="GENERIC",objective_snapshot="EDUCATION",editorial_verdict_snapshot="WORTH_IT",price_verdict_snapshot="FAIR_PRICE",disclosure_text="Afiliado",required_warnings=[],forbidden_claims=[],estimated_duration_seconds=20)
        db.add(row);db.commit();return row.id

@pytest.mark.parametrize("status",["DRAFT","READY_FOR_REVIEW","REJECTED","ARCHIVED"])
def test_only_approved_creative_creates_job(client,status):
    assert client.post(f"/api/v1/media-jobs/from-creative/{creative(status)}",json={"renderType":"PREVIEW"}).status_code==409

@pytest.mark.parametrize("profile,width,height",[("PREVIEW",540,960),("STANDARD",1080,1920)])
def test_media_job_profiles_and_crud(client,profile,width,height):
    made=client.post(f"/api/v1/media-jobs/from-creative/{creative()}",json={"renderType":profile});assert made.status_code==201
    body=made.json();assert (body["width"],body["height"],body["fps"],body["status"])==(width,height,30,"QUEUED")
    assert client.get(f"/api/v1/media-jobs/{body['id']}").json()["renderType"]==profile
    assert any(x["id"]==body["id"] for x in client.get("/api/v1/media-jobs").json())

def png(width=2,height=3):return b"\x89PNG\r\n\x1a\n"+b"\0"*8+width.to_bytes(4,"big")+height.to_bytes(4,"big")+b"data"

def transparent_png(width=2,height=3):return b"\x89PNG\r\n\x1a\n"+b"\0"*8+width.to_bytes(4,"big")+height.to_bytes(4,"big")+bytes([8,6])+b"data"

def test_avatar_upload_classifies_character_state_and_alpha(client,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));response=client.post("/api/v1/media-assets",data={"assetType":"AVATAR_IMAGE","ownerType":"AVATAR","ownerId":"BRUNO","character":"BRUNO","avatarState":"WARNING"},files={"file":("bruno-warning.png",transparent_png(),"image/png")});assert response.status_code==201
    body=response.json();assert body["metadata"]=={"speaker":"BRUNO","state":"WARNING","hasAlpha":True} and (body["width"],body["height"])==(2,3)
    invalid=client.post("/api/v1/media-assets",data={"assetType":"AVATAR_IMAGE","ownerType":"AVATAR","character":"CAROL","avatarState":"COMPARING"},files={"file":("carol.png",transparent_png(),"image/png")});assert invalid.status_code==422

def test_avatar_resolver_exact_neutral_no_cross_character_and_narrator():
    rows=[MediaAsset(id="bruno-neutral",asset_type="AVATAR_IMAGE",owner_type="AVATAR",active=True,metadata_={"speaker":"BRUNO","state":"NEUTRAL"}),MediaAsset(id="bruno-warning",asset_type="AVATAR_IMAGE",owner_type="AVATAR",active=True,metadata_={"speaker":"BRUNO","state":"WARNING"}),MediaAsset(id="carol-question",asset_type="AVATAR_IMAGE",owner_type="AVATAR",active=True,metadata_={"speaker":"CAROL","state":"QUESTIONING"}),MediaAsset(id="carol-neutral-off",asset_type="AVATAR_IMAGE",owner_type="AVATAR",active=False,metadata_={"speaker":"CAROL","state":"NEUTRAL"})]
    class Scalars:
        def all(self):return [x for x in rows if x.active]
    class DB:
        def scalars(self,*args):return Scalars()
    resolver=AssetResolver(DB());assert resolver.avatar("BRUNO","WARNING")==("bruno-warning","EXACT");assert resolver.avatar("BRUNO",None)==("bruno-neutral","EXACT");assert resolver.avatar("CAROL","QUESTIONING")==("carol-question","EXACT")
    assert resolver.avatar("CAROL","THINKING")== (None,"BRAND_FALLBACK") and resolver.avatar("NARRATOR","WARNING")== (None,"NOT_APPLICABLE") and resolver.avatar("NONE",None)==(None,"NOT_APPLICABLE")

def test_missing_avatar_uses_brand_fallback_without_cross_character():
    from apps.api.app.services.media_pipeline import layout
    assert layout("AVATAR",False,False)=="BRAND_FALLBACK" and layout("WARNING",False,False)=="BRAND_FALLBACK"

@pytest.mark.parametrize("width,height",[(540,960),(1080,1920)])
def test_brand_layout_scales_preserves_aspect_and_safe_areas(width,height):
    boxes=layout_boxes(width,height,"MIXED");safe=safe_areas(width,height);fitted=fit_asset(800,1200,boxes["avatar"])
    assert fitted.width/fitted.height==pytest.approx(2/3,rel=.01);assert fitted.x>=0 and fitted.y>=safe.top and fitted.x+fitted.width<=width and fitted.y+fitted.height<=safe.subtitle_top
    assert boxes["product"].x+boxes["product"].width<=boxes["avatar"].x and safe.subtitle_top<height-safe.bottom/2

def test_asset_upload_linkage_list_get_and_deactivate(client,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));response=client.post("/api/v1/media-assets",data={"assetType":"PRODUCT_IMAGE","ownerType":"CANDIDATE","ownerId":"candidate-1","logicalName":"Produto"},files={"file":("../../produto.png",png(),"image/png")});assert response.status_code==201
    body=response.json();assert body["ownerId"]=="candidate-1" and body["width"]==2 and body["height"]==3 and ".." not in body["relativePath"]
    assert body["relativePath"].startswith("assets/") and (tmp_path/body["relativePath"]).exists()
    assert client.get(f"/api/v1/media-assets/{body['id']}").status_code==200
    assert client.get("/api/v1/media-assets?ownerId=candidate-1").json()[0]["id"]==body["id"]
    assert client.delete(f"/api/v1/media-assets/{body['id']}").json()["active"] is False

def test_asset_activation_is_idempotent_and_preserves_identity_path_and_file(client,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));created=client.post("/api/v1/media-assets",data={"assetType":"PRODUCT_IMAGE","ownerType":"CANDIDATE","ownerId":"candidate-1"},files={"file":("produto.png",png(),"image/png")}).json();path=tmp_path/created["relativePath"];original=path.read_bytes();client.delete(f"/api/v1/media-assets/{created['id']}")
    activated=client.post(f"/api/v1/media-assets/{created['id']}/activate");assert activated.status_code==200;body=activated.json();assert body["active"] is True and body["id"]==created["id"] and body["relativePath"]==created["relativePath"] and path.read_bytes()==original
    again=client.post(f"/api/v1/media-assets/{created['id']}/activate");assert again.status_code==200 and again.json()["id"]==created["id"] and again.json()["relativePath"]==created["relativePath"]

def test_activate_missing_asset_returns_404(client):
    assert client.post("/api/v1/media-assets/missing/activate").status_code==404

def test_permanent_asset_removal_deletes_record_and_storage_file(client,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));created=client.post("/api/v1/media-assets",data={"assetType":"PRODUCT_IMAGE","ownerType":"CANDIDATE"},files={"file":("produto.png",png(),"image/png")}).json();path=tmp_path/created["relativePath"];assert path.is_file()
    removed=client.delete(f"/api/v1/media-assets/{created['id']}/permanent");assert removed.status_code==204 and not path.exists()
    with SessionLocal() as db:assert db.get(MediaAsset,created["id"]) is None
    assert client.delete(f"/api/v1/media-assets/{created['id']}/permanent").status_code==404

def test_permanent_asset_removal_rejects_path_outside_storage(client,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));created=client.post("/api/v1/media-assets",data={"assetType":"PRODUCT_IMAGE","ownerType":"CANDIDATE"},files={"file":("produto.png",png(),"image/png")}).json();outside=tmp_path.parent/"outside.png";outside.write_bytes(b"keep")
    with SessionLocal() as db:row=db.get(MediaAsset,created["id"]);row.relative_path="../outside.png";db.commit()
    assert client.delete(f"/api/v1/media-assets/{created['id']}/permanent").status_code==409 and outside.read_bytes()==b"keep"
    with SessionLocal() as db:assert db.get(MediaAsset,created["id"]) is not None

def test_asset_content_is_served_only_from_media_storage(client,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));response=client.post("/api/v1/media-assets",data={"assetType":"PRODUCT_IMAGE","ownerType":"CANDIDATE"},files={"file":("produto.png",png(),"image/png")});asset=response.json()
    content=client.get(f"/api/v1/media-assets/{asset['id']}/content");assert content.status_code==200 and content.content==png()
    with SessionLocal() as db:row=db.get(MediaAsset,asset["id"]);row.relative_path="../outside.png";db.commit()
    assert client.get(f"/api/v1/media-assets/{asset['id']}/content").status_code==404

@pytest.mark.parametrize("name,mime,data",[("x.gif","image/gif",b"GIF89a"),("x.png","image/jpeg",png()),("x.png","image/png",b"not-image")])
def test_asset_validation(client,tmp_path,monkeypatch,name,mime,data):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));assert client.post("/api/v1/media-assets",data={"assetType":"PRODUCT_IMAGE","ownerType":"CANDIDATE"},files={"file":(name,data,mime)}).status_code==422

def test_storage_rejects_traversal_and_is_writable(tmp_path):
    storage=MediaStorage(tmp_path);assert storage.writable()
    with pytest.raises(ValueError):storage.resolve("../outside")

def test_diagnostics_are_mockable_and_never_use_shell(monkeypatch):
    calls=[]
    def run(args,**kwargs):calls.append((args,kwargs));return subprocess.CompletedProcess(args,0,"ffmpeg version 1\n","")
    monkeypatch.setattr(subprocess,"run",run);assert binary_diagnostic("ffmpeg")["status"]=="AVAILABLE";assert calls[0][0]==["ffmpeg","-version"] and calls[0][1]["shell"] is False

def test_diagnostics_tts_not_configured_and_storage_available(client,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"tts_provider","");body=client.get("/api/v1/media/diagnostics").json();assert body["tts"]["status"]=="NOT_CONFIGURED" and body["tts"]["profiles"]["BRUNO"]=={"status":"NOT_CONFIGURED","reasonCode":"MODEL_NOT_CONFIGURED"} and body["storage"]["status"]=="AVAILABLE"

def test_diagnostics_distinguishes_missing_model_and_config(client,tmp_path,monkeypatch):
    executable=tmp_path/"piper.exe";executable.write_bytes(b"x");model=tmp_path/"voice.onnx";model.write_bytes(b"x")
    monkeypatch.setattr(settings,"tts_provider","PIPER");monkeypatch.setattr(settings,"tts_invocation_mode","CLI");monkeypatch.setattr(settings,"tts_executable_path",str(executable));monkeypatch.setattr(settings,"tts_model_bruno",str(tmp_path/"missing.onnx"));monkeypatch.setattr(settings,"tts_model_carol",str(model));monkeypatch.setattr(settings,"tts_model_config_carol","");monkeypatch.setattr(settings,"tts_model_narrator","");body=client.get("/api/v1/media/diagnostics").json()["tts"];assert body["profiles"]["BRUNO"]["reasonCode"]=="MODEL_NOT_FOUND" and body["profiles"]["CAROL"]["reasonCode"]=="MODEL_CONFIG_NOT_FOUND" and body["profiles"]["NARRATOR"]["reasonCode"]=="MODEL_NOT_CONFIGURED"

def test_module_help_exit_zero_is_available_without_synthesis(monkeypatch):
    calls=[]
    def run(args,**kwargs):calls.append(args);return subprocess.CompletedProcess(args,0,"usage: piper","")
    monkeypatch.setattr(subprocess,"run",run);available,version=piper_probe(["python","-m","piper"],"MODULE");assert available and version=="Piper module available" and calls==[["python","-m","piper","--help"]]

def test_cli_falls_back_from_version_to_help(monkeypatch):
    calls=[]
    def run(args,**kwargs):calls.append(args);return subprocess.CompletedProcess(args,0 if args[-1]=="--help" else 2,"usage: piper","")
    monkeypatch.setattr(subprocess,"run",run);assert piper_probe(["piper"],"CLI")== (True,"Piper CLI available");assert calls==[["piper","--version"],["piper","--help"]]

def test_help_failure_is_error(monkeypatch):
    monkeypatch.setattr(subprocess,"run",lambda args,**kwargs:subprocess.CompletedProcess(args,2,"","usage error"));assert piper_probe(["python","-m","piper"],"MODULE")== (False,None)

def test_diagnostics_module_available_with_all_profiles_and_no_synthesis(client,tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x")
    for speaker in ("bruno","carol","narrator"):
        model=tmp_path/f"{speaker}.onnx";model.write_bytes(b"x");(tmp_path/f"{speaker}.onnx.json").write_bytes(b"{}")
        monkeypatch.setattr(settings,f"tts_model_{speaker}",str(model));monkeypatch.setattr(settings,f"tts_model_config_{speaker}","")
    calls=[]
    def run(args,**kwargs):calls.append(args);return subprocess.CompletedProcess(args,0,"usage: piper","")
    monkeypatch.setattr(subprocess,"run",run);monkeypatch.setattr(settings,"tts_provider","PIPER");monkeypatch.setattr(settings,"tts_invocation_mode","MODULE");monkeypatch.setattr(settings,"tts_python_path",str(python));body=client.get("/api/v1/media/diagnostics").json()["tts"];assert body["status"]=="AVAILABLE" and body["version"]=="Piper module available" and all(x["status"]=="AVAILABLE" for x in body["profiles"].values());assert [str(python),"-m","piper","--help"] in calls and not any("--output_file" in x for x in calls)

def test_chatterbox_missing_python_is_not_configured_and_does_not_probe(monkeypatch):
    calls=[];monkeypatch.setattr(subprocess,"run",lambda *a,**k:calls.append(a))
    assert chatterbox_probe("")== ("NOT_CONFIGURED","CHATTERBOX_PYTHON_NOT_CONFIGURED") and calls==[]

def test_chatterbox_diagnostic_import_success_and_failure_without_synthesis(client,tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x");calls=[]
    def run(args,**kwargs):
        calls.append((args,kwargs));return subprocess.CompletedProcess(args,0,"IMPORT_OK\n" if "-c" in args else "ffmpeg version test\n","")
    monkeypatch.setattr(subprocess,"run",run);monkeypatch.setattr(settings,"tts_provider","CHATTERBOX");monkeypatch.setattr(settings,"chatterbox_python_path",str(python))
    for name in ("bruno","carol","narrator"):monkeypatch.setattr(settings,f"chatterbox_reference_{name}","")
    body=client.get("/api/v1/media/diagnostics").json()["tts"];assert body["status"]=="AVAILABLE" and body["provider"]=="CHATTERBOX" and body["invocationMode"]=="ISOLATED" and body["reasonCode"] is None and body["version"]=="Chatterbox import available";probe=next(x for x in calls if "-c" in x[0]);assert probe[0]==[str(python),"-c",CHATTERBOX_IMPORT_PROBE] and probe[1]["shell"] is False and probe[1]["timeout"]==90 and not any("--output" in x[0] or "from_pretrained" in " ".join(x[0]) for x in calls)
    monkeypatch.setattr(subprocess,"run",lambda args,**kwargs:subprocess.CompletedProcess(args,1,"","import failed"));assert client.get("/api/v1/media/diagnostics").json()["tts"]["status"]=="ERROR"

def test_chatterbox_probe_rejects_timeout_and_unexpected_stdout(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x")
    monkeypatch.setattr(subprocess,"run",lambda *args,**kwargs:(_ for _ in ()).throw(subprocess.TimeoutExpired(args[0],kwargs["timeout"],stderr="token=hidden")))
    assert chatterbox_probe(str(python))==("ERROR","CHATTERBOX_IMPORT_FAILED")
    monkeypatch.setattr(subprocess,"run",lambda args,**kwargs:subprocess.CompletedProcess(args,0,"something else\n",""))
    assert chatterbox_probe(str(python))==("ERROR","CHATTERBOX_IMPORT_FAILED")

def test_chatterbox_diagnostic_timeout_is_independent_and_configurable(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x");seen={};monkeypatch.setattr(settings,"chatterbox_diagnostic_timeout_seconds",75);monkeypatch.setattr(settings,"chatterbox_model_load_timeout_seconds",999);monkeypatch.setattr(settings,"chatterbox_synthesis_timeout_seconds",888)
    def run(args,**kwargs):seen.update(kwargs);return subprocess.CompletedProcess(args,0,"IMPORT_OK\n","")
    monkeypatch.setattr(subprocess,"run",run);assert chatterbox_probe(str(python))==("AVAILABLE",None);assert seen["timeout"]==75

def test_chatterbox_diagnostic_timeout_default_is_ninety_seconds():
    from apps.api.app.core.config import Settings
    assert Settings(_env_file=None).chatterbox_diagnostic_timeout_seconds==90

def job_with_scenes(client,status="APPROVED"):
    cid=creative(status)
    with SessionLocal() as db:
        db.add_all([CreativeScene(creative_id=cid,order_index=0,scene_type="PRODUCT",speaker="NARRATOR",purpose="BENEFIT",narration_text="Uma frase curta para teste",duration_seconds=1,required_warning_codes=[]),CreativeScene(creative_id=cid,order_index=1,scene_type="CTA",speaker="NONE",purpose="CTA",narration_text=None,duration_seconds=2,required_warning_codes=[])]);db.commit()
    return client.post(f"/api/v1/media-jobs/from-creative/{cid}",json={"renderType":"PREVIEW"}).json()

def test_fake_start_completes_with_progress_duration_and_logs(client,monkeypatch):
    monkeypatch.setattr(settings,"media_pipeline_mode","FAKE");job=job_with_scenes(client);started=client.post(f"/api/v1/media-jobs/{job['id']}/start");assert started.status_code==200
    final=client.get(f"/api/v1/media-jobs/{job['id']}").json();assert final["status"]=="COMPLETED" and final["progressPercent"]==100 and final["totalScenes"]==2 and final["currentSceneIndex"]==1 and final["expectedDurationSeconds"]>=3 and final["validationStatus"]=="VALID" and final["outputRelativePath"] is None
    with SessionLocal() as db:actions=set(db.scalars(select(DecisionLog.action).where(DecisionLog.entity_id==job["id"])))
    assert {"MEDIA_JOB_STARTED","MEDIA_AUDIO_RENDERED","MEDIA_SCENE_RENDERED","MEDIA_JOB_COMPLETED"}<=actions
    assert client.post(f"/api/v1/media-jobs/{job['id']}/start").status_code==409 and client.post(f"/api/v1/media-jobs/{job['id']}/cancel").status_code==409

def test_completed_video_stream_is_controlled_and_hides_physical_path(client,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));job=job_with_scenes(client);relative="jobs/job/preview/video.mp4";path=tmp_path/relative;path.parent.mkdir(parents=True);path.write_bytes(b"video")
    with SessionLocal() as db:row=db.get(MediaJob,job["id"]);row.status="COMPLETED";row.validation_status="VALID";row.preview_relative_path=relative;db.commit()
    response=client.get(f"/api/v1/media-jobs/{job['id']}/content");assert response.status_code==200 and response.content==b"video" and "video/mp4" in response.headers["content-type"]
    assert str(tmp_path) not in str(response.headers)
    with SessionLocal() as db:row=db.get(MediaJob,job["id"]);row.preview_relative_path="../outside.mp4";db.commit()
    assert client.get(f"/api/v1/media-jobs/{job['id']}/content").status_code==404

def test_completed_job_uses_ffprobe_validated_duration(client):
    class ValidatedDuration(FakeMediaValidator):
        def validate(self,output):return {"status":"VALID","details":{"durationSeconds":29.9}}
    job=job_with_scenes(client)
    with SessionLocal() as db:
        row=db.get(MediaJob,job["id"]);row.status="PREPARING";db.commit();run_pipeline(db,row.id,voice=FakeVoiceRenderer(),scene_renderer=FakeSceneRenderer(),composer=FakeTimelineComposer(),validator=ValidatedDuration());db.refresh(row);assert row.actual_duration_seconds==30 and row.validation_details["durationSeconds"]==29.9

def test_real_audio_duration_drives_precise_cumulative_timeline_and_silent_scene_keeps_configured_duration(client):
    class Voice:
        def render(self,spec):return {"audioId":spec.scene_id,"durationSeconds":3.742}
    class Scenes(FakeSceneRenderer):
        def __init__(self):super().__init__();self.specs=[]
        def render(self,spec,audio,width,height):self.specs.append(spec);return super().render(spec,audio,width,height)
    class Validator:
        def validate(self,output):return {"status":"VALID","details":{"durationSeconds":output["durationSeconds"],"audioTimelineDuration":output["durationSeconds"],"timelineDriftMilliseconds":0}}
    renderer=Scenes();job=job_with_scenes(client)
    with SessionLocal() as db:
        row=db.get(MediaJob,job["id"]);row.status="PREPARING";db.commit();run_pipeline(db,row.id,voice=Voice(),scene_renderer=renderer,composer=FakeTimelineComposer(),validator=Validator());db.refresh(row)
        first,second=renderer.specs;assert first.resolved_duration_seconds==pytest.approx(3.742) and first.timeline_start_seconds==0 and first.timeline_end_seconds==pytest.approx(3.742)
        assert first.subtitle_start_seconds==0 and first.subtitle_end_seconds==pytest.approx(3.742);assert second.resolved_duration_seconds==2 and second.timeline_start_seconds==pytest.approx(3.742) and second.timeline_end_seconds==pytest.approx(5.742)
        assert db.get(MediaJob,job["id"]).validation_details["audioTimelineDuration"]==pytest.approx(5.742)
        logs=db.scalars(select(DecisionLog).where(DecisionLog.entity_id==job["id"],DecisionLog.action=="MEDIA_SCENE_RENDERED").order_by(DecisionLog.timestamp)).all();assert logs[0].metadata_["audioDurationSeconds"]==pytest.approx(3.742) and logs[1].metadata_["timelineStartSeconds"]==pytest.approx(3.742)

def test_local_mode_rejects_without_changing_job(client,monkeypatch):
    monkeypatch.setattr(settings,"media_pipeline_mode","LOCAL");job=job_with_scenes(client);assert client.post(f"/api/v1/media-jobs/{job['id']}/start").status_code==409;assert client.get(f"/api/v1/media-jobs/{job['id']}").json()["status"]=="QUEUED"

def test_cancel_queued(client):
    job=job_with_scenes(client);body=client.post(f"/api/v1/media-jobs/{job['id']}/cancel").json();assert body["status"]=="CANCELED" and body["errorCode"]=="JOB_CANCELED"

@pytest.mark.parametrize("adapter,error",[(FakeVoiceRenderer(True),"VOICE_RENDER_FAILED"),(FakeSceneRenderer(0),"SCENE_RENDER_FAILED"),(FakeTimelineComposer(True),"COMPOSE_FAILED"),(FakeMediaValidator("INVALID"),"MEDIA_VALIDATION_FAILED")])
def test_pipeline_failures_are_persisted(client,adapter,error):
    job=job_with_scenes(client)
    with SessionLocal() as db:
        row=db.get(MediaJob,job["id"]);row.status="PREPARING";db.commit();kwargs={"voice":FakeVoiceRenderer(),"scene_renderer":FakeSceneRenderer(),"composer":FakeTimelineComposer(),"validator":FakeMediaValidator()}
        if isinstance(adapter,FakeVoiceRenderer):kwargs["voice"]=adapter
        elif isinstance(adapter,FakeSceneRenderer):kwargs["scene_renderer"]=adapter
        elif isinstance(adapter,FakeTimelineComposer):kwargs["composer"]=adapter
        else:kwargs["validator"]=adapter
        run_pipeline(db,row.id,**kwargs);db.refresh(row);assert row.status=="FAILED" and row.error_code==error and row.progress_percent<100

def test_scene_specs_asset_and_avatar_fallbacks(client):
    job=job_with_scenes(client)
    with SessionLocal() as db:
        media_job=db.get(MediaJob,job["id"]);creative_row=db.get(Creative,media_job.creative_id);campaign=db.get(Campaign,creative_row.campaign_id);scene=db.scalar(select(CreativeScene).where(CreativeScene.creative_id==creative_row.id));scene.avatar_state="WARNING";scene.scene_type="AVATAR";scene.speaker="BRUNO"
        product=MediaAsset(asset_type="PRODUCT_IMAGE",owner_type="CANDIDATE",owner_id=campaign.candidate_id,logical_name="produto",relative_path="assets/product.png",mime_type="image/png",file_size_bytes=1,active=True);neutral=MediaAsset(asset_type="AVATAR_IMAGE",owner_type="AVATAR",logical_name="bruno",relative_path="assets/bruno.png",mime_type="image/png",file_size_bytes=1,metadata_={"speaker":"BRUNO","state":"NEUTRAL"},active=True);db.add_all([product,neutral]);db.commit();spec=build_specs(db,creative_row,[scene])[0];assert spec.product_asset_ids==[product.id] and spec.avatar_asset_id==neutral.id and spec.layout_type=="AVATAR" and spec.disclosure_text is None
        neutral.active=False;db.commit();spec=build_specs(db,creative_row,[scene])[0];assert spec.avatar_asset_id is None and spec.layout_type=="BRAND_FALLBACK"

def test_scene_specs_normalize_duplicate_order_indexes_for_unique_artifacts(client):
    job=job_with_scenes(client)
    with SessionLocal() as db:
        media_job=db.get(MediaJob,job["id"]);creative_row=db.get(Creative,media_job.creative_id);scenes=db.scalars(select(CreativeScene).where(CreativeScene.creative_id==creative_row.id).order_by(CreativeScene.order_index)).all();scenes[1].order_index=scenes[0].order_index;db.flush();specs=build_specs(db,creative_row,scenes);assert [x.order_index for x in specs]==list(range(len(specs))) and len({x.scene_id for x in specs})==len(specs)

def test_audio_estimate_extends_scene():
    from apps.api.app.services.media_pipeline import SceneRenderSpec
    spec=SceneRenderSpec("s",0,"TEXT","NARRATOR","um dois três quatro cinco seis sete oito",None,None,None,1,1,[],None,None,[],"TEXT");audio=FakeVoiceRenderer().render(spec);assert audio["durationSeconds"]>1

def test_recovery_only_fails_active_jobs(client):
    active=job_with_scenes(client);queued=job_with_scenes(client);completed=job_with_scenes(client)
    with SessionLocal() as db:
        db.get(MediaJob,active["id"]).status="COMPOSING";db.get(MediaJob,completed["id"]).status="COMPLETED";db.commit();assert recover_interrupted(db)==1;assert db.get(MediaJob,active["id"]).error_code=="JOB_INTERRUPTED" and db.get(MediaJob,queued["id"]).status=="QUEUED" and db.get(MediaJob,completed["id"]).status=="COMPLETED"
