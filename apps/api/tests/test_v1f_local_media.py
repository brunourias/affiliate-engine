import json,subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from apps.api.app.core.config import settings
from apps.api.app.services.ffmpeg_adapter import FFmpegAdapter,MediaProcessError,escape_filtergraph_path
from apps.api.app.services.local_media import ChatterboxVoiceRenderer,LocalMediaValidator,LocalSceneRenderer,LocalTimelineComposer,PiperVoiceRenderer,safe_slug,voice_renderer
from apps.api.app.services.media_pipeline import SceneRenderSpec
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.motion import select_motion
from apps.api.app.services.subtitle_renderer import SubtitleRenderer,blocks,cue_weight,cues,timestamp
from apps.api.app.db.models import MediaJob
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.voice_engine import TTSNormalizer
from apps.api.app.services.voice_director import FINAL_TIMING_PACE_ADJUSTMENT,compress_script,direction_for_purpose,final_timing_speed,pace_target_status,provider_parameters,timing_polish
from apps.api.app.services.shot_director import ShotDirector,visual_checks
from apps.api.app.services.voice_synthesis_guard import VoiceSynthesisGuard
from apps.api.app.services.commercial_polish import dead_air_metrics,headline_redundancy,polish_headline,polish_shots,shot_delta
from apps.api.app.services.product_media import BrollDirector,ProductMediaAnalyzer,repetition_metrics

class Adapter:
    def __init__(self,probe=None):self.calls=[];self.data=probe or {"streams":[{"codec_type":"video","codec_name":"h264","width":540,"height":960},{"codec_type":"audio","codec_name":"aac"}],"format":{"duration":"3.2"}}
    def run(self,args,**kwargs):
        self.calls.append((args,kwargs));Path(args[args.index("--output_file")+1]).write_bytes(b"WAV") if "--output_file" in args else None;return subprocess.CompletedProcess(args,0,"piper 1","")
    def audio_duration(self,path):return 3.2
    def render_scene(self,args):self.calls.append((args,{}));Path(args[-1]).write_bytes(b"MP4")
    def compose(self,args):self.calls.append((args,{}));Path(args[-1]).write_bytes(b"MP4")
    def probe(self,path):return self.data
    def trim_audio_edges(self,source,target,*args):self.calls.append((["trim",str(source),str(target),*args],{}));Path(target).write_bytes(Path(source).read_bytes())

def test_product_media_analyzer_groups_duplicates_and_declares_real_diversity(tmp_path,monkeypatch):
    rows=[SimpleNamespace(id="a",asset_type="PRODUCT_IMAGE",relative_path="a.png",width=600,height=800,metadata_={"classification":"HERO_IMAGE"}),SimpleNamespace(id="b",asset_type="PRODUCT_IMAGE",relative_path="b.png",width=300,height=400,metadata_={"classification":"ALTERNATE_IMAGE"}),SimpleNamespace(id="c",asset_type="PRODUCT_IMAGE",relative_path="c.png",width=600,height=800,metadata_={"classification":"DETAIL_IMAGE"})]
    for name in ("a.png","b.png","c.png"):(tmp_path/name).write_bytes(name.encode())
    class Scalars:
        def all(self):return rows
    class DB:
        def scalars(self,_query):return Scalars()
    monkeypatch.setattr(MediaStorage,"resolve",lambda self,path:tmp_path/path);fingerprints={"a.png":"dh:0000000000000000","b.png":"dh:0000000000000001","c.png":"dh:ffffffffffffffff"};monkeypatch.setattr("apps.api.app.services.product_media.perceptual_fingerprint",lambda path:fingerprints[path.name])
    bundle=ProductMediaAnalyzer().analyze(DB(),"candidate")
    assert bundle["assetCount"]==3 and bundle["uniqueVisualGroups"]==2 and bundle["diversityLevel"]=="MEDIUM"
    assert bundle["assets"][0]["duplicateGroup"]==bundle["assets"][1]["duplicateGroup"]!=bundle["assets"][2]["duplicateGroup"]

def test_single_product_asset_warns_without_faking_diversity(tmp_path,monkeypatch):
    row=SimpleNamespace(id="a",asset_type="PRODUCT_IMAGE",relative_path="a.png",width=456,height=465,metadata_={})
    (tmp_path/"a.png").write_bytes(b"a")
    class Scalars:
        def all(self):return [row]
    class DB:
        def scalars(self,_query):return Scalars()
    monkeypatch.setattr(MediaStorage,"resolve",lambda self,path:tmp_path/path);monkeypatch.setattr("apps.api.app.services.product_media.perceptual_fingerprint",lambda _path:"dh:0")
    bundle=ProductMediaAnalyzer().analyze(DB(),"candidate")
    assert bundle["diversityLevel"]=="LOW" and bundle["qualityCheck"]=="WARNING" and bundle["uniqueVisualGroups"]==1

def test_broll_director_is_deterministic_and_uses_source_cooldown():
    assets=[{"assetId":value,"classification":"HERO_IMAGE","qualityScore":80,"duplicateGroup":value,"mediaType":"PRODUCT_IMAGE","warnings":[]} for value in ("a","b","c")];bundle={"assets":assets};shots=[object() for _ in range(5)]
    first=BrollDirector().assign(shots,"HOOK",bundle);second=BrollDirector().assign(shots,"HOOK",bundle)
    assert [x["assetId"] for x in first]==[x["assetId"] for x in second]
    assert all(left["duplicateGroup"]!=right["duplicateGroup"] for left,right in zip(first,first[1:]))
    assert repetition_metrics(first)["uniqueSourceAssets"]==3

def test_product_video_is_looped_as_visual_only_and_does_not_replace_narration(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));clip=tmp_path/"clip.mp4";clip.write_bytes(b"video")
    asset=SimpleNamespace(id="clip",relative_path="clip.mp4",asset_type="PRODUCT_VIDEO")
    class DB:
        def get(self,_model,_asset_id):return asset
    adapter=Adapter();LocalSceneRenderer(DB(),"video",adapter).render(spec(layout_type="PRODUCT",product_asset_ids=["clip"]),None,540,960);args=adapter.calls[-1][0]
    assert "-stream_loop" in args and str(clip) in args
    assert args[args.index("-map",args.index("-filter_complex"))+3].endswith(":a:0")
    assert args[args.index("-map",args.index("-filter_complex"))+3]!=f"{args.index(str(clip))}:a:0"

def spec(**changes):
    values=dict(scene_id="s1",order_index=0,scene_type="TEXT",speaker="NARRATOR",narration_text="Texto seguro -- sem execução",on_screen_text="Na tela",visual_instruction="não executar",avatar_state=None,requested_duration_seconds=2,resolved_duration_seconds=3.8,product_asset_ids=[],avatar_asset_id=None,disclosure_text=None,required_warning_codes=[],layout_type="TEXT",avatar_resolution="NOT_APPLICABLE");values.update(changes);return SceneRenderSpec(**values)

def test_mixed_renderer_uses_product_and_transparent_avatar_without_overflow(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));product=tmp_path/"product.png";avatar=tmp_path/"avatar.png";product.write_bytes(b"p");avatar.write_bytes(b"a")
    class DB:
        def get(self,_model,asset_id):return SimpleNamespace(relative_path=f"{asset_id}.png")
    adapter=Adapter();result=LocalSceneRenderer(DB(),"mixed",adapter).render(spec(layout_type="MIXED",product_asset_ids=["product"],avatar_asset_id="avatar"),None,540,960);args=adapter.calls[-1][0];graph=args[args.index("-filter_complex")+1]
    assert args.count(str(product))>=2 and str(avatar) in args and graph.count("format=rgba")>=2 and "overlay=" in graph and "eval=frame" in graph
    assert "boxblur=20:2" in graph and "force_original_aspect_ratio=increase" in graph and result["motion"]["shotCount"]>=2
    assert result["motion"]["patternInterruptCount"]>=1 and result["motion"]["maxVisualStagnationSeconds"]<=2.5
    assert "fade=t=in" in graph and "fade=t=out" in graph and graph.index("fade=t=out")<graph.index("ass=")


@pytest.mark.parametrize("width,height,expected_float",[(540,960,6),(1080,1920,12)])
def test_motion_is_deterministic_and_proportional(width,height,expected_float):
    first=select_motion("MIXED",2,True,True,width,height);second=select_motion("MIXED",2,True,True,width,height)
    assert first==second and first.product_motion=="SLOW_ZOOM_IN" and first.avatar_motion=="STATIC"
    assert first.avatar_float_pixels==expected_float


def test_layout_motion_rules_are_subtle_and_independent():
    product=select_motion("PRODUCT",1,True,False,540,960);avatar=select_motion("AVATAR",0,False,True,540,960);mixed=select_motion("MIXED",0,True,True,540,960)
    assert product.product_motion=="SLOW_ZOOM_OUT" and product.avatar_motion=="STATIC"
    assert avatar.product_motion=="STATIC" and avatar.avatar_motion=="STATIC"
    assert mixed.product_motion=="SLOW_ZOOM_IN" and mixed.avatar_motion=="STATIC"

def test_shot_director_is_deterministic_exact_and_varied_without_changing_audio():
    director=ShotDirector();first=director.plan("PROBLEM","PRODUCT",4.0,True,True,"USO EM CASA");second=director.plan("PROBLEM","PRODUCT",4.0,True,True,"USO EM CASA")
    assert first==second and len(first)>=2 and first[0].start==0 and first[-1].end==4.0
    assert sum(x.end-x.start for x in first)==pytest.approx(4.0) and max(x.end-x.start for x in first)<=2.5
    assert max(x.scale_end for x in first)>.60 and len({x.shot_type for x in first})>1 and any(not x.persona_visible for x in first)
    assert set(visual_checks(first,4.0,"PROBLEM").values())=={"PASS"}

def test_hook_and_cta_use_strong_product_compositions_and_safe_headlines():
    hook=ShotDirector().plan("HOOK","PRODUCT_HERO",2.0,True,True,"PRECISA MESMO DE UMA PROFISSIONAL?");cta=ShotDirector().plan("CTA","CTA",2.0,True,True,"CONFIRA OS DETALHES")
    assert hook[0].shot_type=="CLOSEUP" and hook[0].scale_end>=.90 and hook[0].text_layout in {"CENTER_PUNCH","TOP_BANNER"}
    assert cta[0].scale_end>=.90 and cta[0].persona_visible is False and visual_checks(cta,2.0,"CTA")["CTA_VISUAL_STRENGTH"]=="PASS"

def test_commercial_polish_detects_redundancy_and_preserves_distinct_headline():
    assert headline_redundancy("USO EM CASA","Uma ferramenta para usar em casa")>=.6
    polished,adjusted,status=polish_headline("PROBLEM","USO EM CASA","Se é só pra usar em casa, provavelmente não.");assert adjusted and polished=="NÃO PRECISA EXAGERAR" and status=="PASS"
    unchanged,adjusted,status=polish_headline("VALUE","BOA ESCOLHA","Um modelo simples pode dar conta.");assert unchanged=="BOA ESCOLHA" and not adjusted and status=="PASS"

def test_commercial_polish_enforces_visual_delta_cta_hold_and_dead_air_limits():
    shots=ShotDirector().plan("CTA","CTA",4.2,True,True,"VEJA PREÇO E DETALHES");polished,adjusted,status=polish_shots(shots,"CTA")
    assert polished[-1].end-polished[-1].start==pytest.approx(1.8) and all(shot_delta(a,b)>=2 for a,b in zip(polished,polished[1:])) and status=="PASS"
    metrics=dead_air_metrics([{"voiceMetadata":{"pauseAfterMs":50}},{"voiceMetadata":{"pauseBeforeMs":20,"pauseAfterMs":90}},{"voiceMetadata":{"pauseBeforeMs":30}}]);assert metrics=={"maxGapMilliseconds":120,"gapsOver150Ms":0,"gapsOver250Ms":0,"gapsOver500Ms":0}


def test_avatar_motion_preserves_rgba_safe_box_and_duration(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));avatar=tmp_path/"avatar.png";avatar.write_bytes(b"a")
    class DB:
        def get(self,_model,_asset_id):return SimpleNamespace(relative_path="avatar.png")
    adapter=Adapter();result=LocalSceneRenderer(DB(),"avatar-motion",adapter).render(spec(layout_type="AVATAR",speaker="BRUNO",avatar_asset_id="avatar",resolved_duration_seconds=4.25),None,540,960)
    args=adapter.calls[-1][0];graph=args[args.index("-filter_complex")+1]
    assert "format=rgba" in graph and "alpha=1" in graph and "*(1-t/4.250000)" not in graph
    assert result["durationSeconds"]==4.25 and args[args.index("-t")+1]=="4.250"


def test_scene_without_assets_keeps_duration_subtitle_and_internal_fade(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));adapter=Adapter();result=LocalSceneRenderer(SimpleNamespace(get=lambda *_:None),"fallback-motion",adapter).render(spec(layout_type="BRAND_FALLBACK",resolved_duration_seconds=2.75),None,1080,1920)
    args=adapter.calls[-1][0];graph=args[args.index("-vf")+1]
    assert "fade=t=in" in graph and graph.index("fade=t=out")<graph.index("ass=")
    assert result["durationSeconds"]==2.75 and result["motion"]["motionPreset"]=="STATIC"

def test_ffmpeg_adapter_uses_argument_list_and_shell_false(monkeypatch):
    seen={}
    def run(args,**kwargs):seen.update(kwargs);assert isinstance(args,list);return subprocess.CompletedProcess(args,0,"ffmpeg version test\n","")
    monkeypatch.setattr(subprocess,"run",run);assert FFmpegAdapter().version("ffmpeg")=="ffmpeg version test" and seen["shell"] is False

def test_voice_director_varies_hook_warning_and_cta_using_supported_controls_only():
    hook=direction_for_purpose("HOOK");warning=direction_for_purpose("WARNING");cta=direction_for_purpose("CTA");base={"exaggeration":.6,"cfgWeight":.4}
    assert hook.voice_style=="CURIOUS_ENERGETIC" and warning.voice_style=="CAUTION" and cta.voice_style=="CONFIDENT_INVITING"
    assert provider_parameters(hook,base)!=provider_parameters(warning,base)!=provider_parameters(cta,base)
    assert set(provider_parameters(hook,base))=={"exaggeration","cfgWeight"} and hook.pause_before_ms==0 and warning.pause_after_ms>hook.pause_after_ms

def test_voice_postprocess_uses_tempo_and_explicit_short_pauses(monkeypatch,tmp_path):
    seen={};adapter=FFmpegAdapter(ffmpeg="ffmpeg");monkeypatch.setattr(adapter,"run",lambda args,**kwargs:seen.setdefault("args",args));adapter.direct_voice(tmp_path/"in.wav",tmp_path/"out.wav",1.2,40,70);audio_filter=seen["args"][seen["args"].index("-af")+1]
    assert "atempo=1.200" in audio_filter and "adelay=40:all=1" in audio_filter and "apad=pad_dur=0.070" in audio_filter and str(settings.media_audio_padding_seconds) not in audio_filter

def test_pace_target_and_deterministic_compression_preserve_facts():
    source=["Agora, pra serviço pesado ou uso todo dia, eu já compararia com modelos mais robustos.","Preço verificado: R$ 199."];compressed=compress_script(source)
    assert pace_target_status(20.5)=="PASS" and pace_target_status(20.51)=="WARNING" and pace_target_status(25.01)=="FAIL"
    assert timing_polish("Dá uma olhada nos detalhes e no preço atual antes de escolher.","CTA")=="Veja os detalhes e o preço atual antes de escolher."
    assert timing_polish("Texto essencial sem alteração.","VALUE")=="Texto essencial sem alteração."
    assert FINAL_TIMING_PACE_ADJUSTMENT==1.06 and FINAL_TIMING_PACE_ADJUSTMENT<=1.08
    assert final_timing_speed(direction_for_purpose("CTA"))==pytest.approx(direction_for_purpose("CTA").speed*1.06,abs=.001)
    assert "R$ 199" in compressed[1] and "modelos mais robustos" in compressed[0] and len(" ".join(compressed))<len(" ".join(source))

def test_voice_synthesis_guard_rejects_real_scene_four_outlier_but_accepts_normal_duration():
    text="O mais importante é não pagar por uma ferramenta muito além do uso que você vai fazer.";guard=VoiceSynthesisGuard();normal=guard.validate(text,3.62);outlier=guard.validate(text,25.039)
    assert normal.status=="VALID" and outlier.status=="REJECTED" and outlier.reason=="DURATION_OUTLIER" and outlier.maximum_duration<21.907

def test_ffmpeg_error_is_sanitized(monkeypatch):
    monkeypatch.setattr(subprocess,"run",lambda *a,**k:(_ for _ in ()).throw(subprocess.CalledProcessError(1,a[0],stderr="filter failed; token=do-not-expose")))
    with pytest.raises(MediaProcessError,match="Ferramenta local") as raised:FFmpegAdapter().run(["ffmpeg","-version"])
    assert raised.value.sanitized_stderr=="filter failed; token=<redacted>" and "do-not-expose" not in str(raised.value)

def test_filtergraph_path_escapes_windows_drive_and_metacharacters():
    value=escape_filtergraph_path(r"C:\Users\operator\affiliate-engine\data\media\jobs\abc\subtitles\scene_001.ass")
    assert value==r"'C\:/Users/operator/affiliate-engine/data/media/jobs/abc/subtitles/scene_001.ass'"
    assert "ass=C:/Users/" not in f"ass={value}"
    assert escape_filtergraph_path(r"C:\media\client's,[draft];scene.ass")==r"'C\:/media/client'\''s,[draft];scene.ass'"

def test_piper_uses_stdin_safe_args_and_job_wav(tmp_path,monkeypatch):
    executable=tmp_path/"piper.exe";model=tmp_path/"model.onnx";config=tmp_path/"model.onnx.json"
    for path in (executable,model,config):path.write_bytes(b"x")
    monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"tts_invocation_mode","CLI");monkeypatch.setattr(settings,"tts_executable_path",str(executable));monkeypatch.setattr(settings,"tts_model_narrator",str(model));monkeypatch.setattr(settings,"tts_model_config_narrator",str(config));adapter=Adapter();result=PiperVoiceRenderer("job",adapter).render(spec());args,kwargs=adapter.calls[0];assert args==[str(executable),"--model",str(model),"--config",str(config),"--output_file",str(tmp_path/"jobs/job/audio/scene_001.wav")];assert kwargs["input_text"]=="Texto seguro -- sem execução" and result["durationSeconds"]==3.2

def test_piper_python_module_mode_uses_safe_argument_list(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";model=tmp_path/"voice.onnx";config=tmp_path/"voice.onnx.json"
    for path in (python,model,config):path.write_bytes(b"x")
    monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"tts_invocation_mode","MODULE");monkeypatch.setattr(settings,"tts_python_path",str(python));monkeypatch.setattr(settings,"tts_python_module","piper");monkeypatch.setattr(settings,"tts_model_narrator",str(model));monkeypatch.setattr(settings,"tts_model_config_narrator",str(config));adapter=Adapter();PiperVoiceRenderer("job",adapter).render(spec());assert adapter.calls[0][0][:3]==[str(python),"-m","piper"]

def test_voice_renderer_selects_configured_provider_without_fallback(monkeypatch):
    monkeypatch.setattr(settings,"tts_provider","PIPER");assert isinstance(voice_renderer("job",Adapter()),PiperVoiceRenderer)
    monkeypatch.setattr(settings,"tts_provider","CHATTERBOX");assert isinstance(voice_renderer("job",Adapter()),ChatterboxVoiceRenderer)
    monkeypatch.setattr(settings,"tts_provider","UNKNOWN")
    with pytest.raises(Exception,match="Provider de voz"):voice_renderer("job",Adapter())

class ChatterboxAdapter(Adapter):
    def run(self,args,**kwargs):
        self.calls.append((args,kwargs));payload=json.loads(kwargs["input_text"])
        for item in payload["items"]:Path(item["output"]).write_bytes(b"WAV")
        result={"modelLoadDuration":2.0,"synthesisDuration":1.0,"totalDuration":3.1,"scenes":[]};return subprocess.CompletedProcess(args,0,"AFFILIATE_RESULT="+json.dumps(result),"")

@pytest.mark.parametrize("speaker,exaggeration,cfg",[("BRUNO","0.6","0.4"),("CAROL","0.6","0.4"),("NARRATOR","0.5","0.45")])
def test_chatterbox_uses_isolated_safe_process_profile_and_real_duration(tmp_path,monkeypatch,speaker,exaggeration,cfg):
    python=tmp_path/"python.exe";python.write_bytes(b"x");monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"chatterbox_python_path",str(python));monkeypatch.setattr(settings,f"chatterbox_reference_{speaker.lower()}","")
    adapter=ChatterboxAdapter();editorial="Conheça os móveis -- sem virar comando";result=ChatterboxVoiceRenderer("job",adapter,TTSNormalizer({"móveis":"mobílias"})).render(spec(speaker=speaker,narration_text=editorial));args,kwargs=adapter.calls[0];item=json.loads(kwargs["input_text"])["items"][0]
    assert isinstance(args,list) and args==[str(python),args[1],"--batch"] and float(item["exaggeration"])==float(exaggeration) and float(item["cfgWeight"])==float(cfg)
    assert item["text"]=="Conheça os mobílias -- sem virar comando." and editorial=="Conheça os móveis -- sem virar comando" and result["durationSeconds"]==3.2

def test_chatterbox_optional_reference_must_be_inside_media_storage(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x");reference=tmp_path/"references"/"voice.wav";reference.parent.mkdir();reference.write_bytes(b"wav")
    monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"chatterbox_python_path",str(python));monkeypatch.setattr(settings,"chatterbox_reference_narrator","references/voice.wav");adapter=ChatterboxAdapter();ChatterboxVoiceRenderer("job",adapter).render(spec());item=json.loads(adapter.calls[0][1]["input_text"])["items"][0];assert item["reference"]==str(reference)
    outside=tmp_path.parent/"outside.wav";outside.write_bytes(b"wav");monkeypatch.setattr(settings,"chatterbox_reference_narrator",str(outside))
    with pytest.raises(Exception,match="Reference audio"):ChatterboxVoiceRenderer("job2",adapter).render(spec())

def test_tts_normalizer_is_deterministic_and_does_not_mutate_editorial_text():
    editorial="Móveis e imóveis. móveis.";normalized=TTSNormalizer({"móveis":"mobílias"}).normalize(editorial)
    assert normalized=="mobílias e imóveis. mobílias." and editorial=="Móveis e imóveis. móveis."
    assert TTSNormalizer().normalize("Confira antes de comprar")=="Confira antes de comprar."

def test_chatterbox_rejects_empty_or_zero_duration_wav(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x");monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"chatterbox_python_path",str(python));monkeypatch.setattr(settings,"chatterbox_reference_narrator","")
    class Empty(ChatterboxAdapter):
        def run(self,args,**kwargs):
            self.calls.append((args,kwargs));payload=json.loads(kwargs["input_text"]);Path(payload["items"][0]["output"]).write_bytes(b"");return subprocess.CompletedProcess(args,0,'AFFILIATE_RESULT={"modelLoadDuration":1,"synthesisDuration":1}',"")
    with pytest.raises(Exception,match="WAV válido"):ChatterboxVoiceRenderer("empty",Empty()).render(spec())
    class Zero(ChatterboxAdapter):
        def audio_duration(self,path):return 0
    with pytest.raises(Exception,match="anormal"):ChatterboxVoiceRenderer("zero",Zero()).render(spec())

def test_chatterbox_retries_only_outlier_scene_and_accepts_second_attempt(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x");monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"chatterbox_python_path",str(python));monkeypatch.setattr(settings,"chatterbox_reference_narrator","")
    class OutlierThenValid(ChatterboxAdapter):
        def audio_duration(self,path):
            name=Path(path).name
            if "attempt_2" in name:return 3.62
            if "raw" in str(path) or "trimmed" in name:return 25.039
            return 3.29
    adapter=OutlierThenValid();renderer=ChatterboxVoiceRenderer("guard-retry",adapter);result=renderer.render(spec(narration_text="O mais importante é não pagar por uma ferramenta muito além do uso que você vai fazer."));runner_calls=[x for x in adapter.calls if "--batch" in x[0]]
    assert len(runner_calls)==2 and result["durationSeconds"]==pytest.approx(3.29) and [x["validationStatus"] for x in renderer.synthesis_events]==["REJECTED","VALID"]
    assert result["voiceMetadata"]["synthesisAttempts"][0]["rejectionReason"]=="DURATION_OUTLIER"

def test_chatterbox_three_outliers_fail_explicitly_without_atempo(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x");monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"chatterbox_python_path",str(python));monkeypatch.setattr(settings,"chatterbox_reference_narrator","")
    class AlwaysOutlier(ChatterboxAdapter):
        def audio_duration(self,path):return 25.039
    adapter=AlwaysOutlier()
    with pytest.raises(Exception) as raised:ChatterboxVoiceRenderer("guard-fail",adapter).render(spec(narration_text="O mais importante é não pagar por uma ferramenta muito além do uso que você vai fazer."))
    payloads=[json.loads(x[1]["input_text"])["items"][0] for x in adapter.calls if "--batch" in x[0]]
    assert raised.value.code=="VOICE_SYNTHESIS_OUTLIER" and len(raised.value.details["attempts"])==3 and len(payloads)==3
    assert payloads[2]["exaggeration"]<=.58 and not any(x[0][0]=="direct" for x in adapter.calls)

def test_chatterbox_failure_is_clear_and_never_falls_back_to_piper(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x");monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"chatterbox_python_path",str(python));monkeypatch.setattr(settings,"chatterbox_reference_narrator","")
    class Failing(Adapter):
        def run(self,args,**kwargs):self.calls.append((args,kwargs));raise MediaProcessError("failed","provider=CHATTERBOX; token=hidden")
    adapter=Failing()
    with pytest.raises(Exception,match="Não foi possível gerar a voz") as raised:ChatterboxVoiceRenderer("failed",adapter).render(spec())
    assert len(adapter.calls)==1 and "chatterbox_tts.py" in adapter.calls[0][0][1] and raised.value.__cause__.sanitized_stderr=="provider=CHATTERBOX; token=<redacted>"

def test_chatterbox_batches_multiple_scenes_with_one_model_process_and_separate_outputs(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x");monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"chatterbox_python_path",str(python));monkeypatch.setattr(settings,"chatterbox_reference_narrator","");adapter=ChatterboxAdapter();renderer=ChatterboxVoiceRenderer("batch-job",adapter)
    results=renderer.render_batch([spec(order_index=0),spec(scene_id="s2",order_index=2,narration_text="Segunda narração")]);payload=json.loads(adapter.calls[0][1]["input_text"])
    assert len([x for x in adapter.calls if "--batch" in x[0]])==1 and adapter.calls[0][0][-1]=="--batch" and [x["sceneIndex"] for x in payload["items"]]==[0,2]
    assert results[0]["path"].name=="scene_001.wav" and results[1]["path"].name=="scene_003.wav" and all(x["path"].is_file() for x in results)
    assert renderer.last_metrics["modelLoadDuration"]==2.0 and renderer.last_metrics["sceneCount"]==2

def test_chatterbox_preserves_raw_wav_and_trims_only_file_edges(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x");monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"chatterbox_python_path",str(python));monkeypatch.setattr(settings,"chatterbox_reference_narrator","");adapter=ChatterboxAdapter();result=ChatterboxVoiceRenderer("trim",adapter).render(spec())
    raw=tmp_path/"jobs/trim/audio/raw/scene_001.wav";assert raw.read_bytes()==b"WAV" and result["path"].read_bytes()==b"WAV";trim=next(x for x in adapter.calls if x[0][0]=="trim");assert trim[0][1]==str(raw) and trim[0][2].endswith("scene_001_trimmed.wav")

def test_ffmpeg_edge_trim_uses_reverse_pass_and_preserves_internal_pauses(monkeypatch,tmp_path):
    seen={};source=tmp_path/"raw.wav";target=tmp_path/"final.wav";source.write_bytes(b"wav");adapter=FFmpegAdapter(ffmpeg="ffmpeg");monkeypatch.setattr(adapter,"run",lambda args,**kwargs:seen.setdefault("args",args));adapter.trim_audio_edges(source,target,-50,.15,.1);audio_filter=seen["args"][seen["args"].index("-af")+1]
    assert audio_filter.count("silenceremove=")==2 and audio_filter.count("areverse")==2 and "stop_periods" not in audio_filter

def test_chatterbox_batch_timeout_is_bounded_and_has_technical_reason(tmp_path,monkeypatch):
    python=tmp_path/"python.exe";python.write_bytes(b"x");monkeypatch.setattr(settings,"media_root",str(tmp_path));monkeypatch.setattr(settings,"chatterbox_python_path",str(python));monkeypatch.setattr(settings,"chatterbox_reference_narrator","");monkeypatch.setattr(settings,"chatterbox_model_load_timeout_seconds",300);monkeypatch.setattr(settings,"chatterbox_synthesis_timeout_seconds",180)
    class Timeout(Adapter):
        def run(self,args,**kwargs):self.calls.append((args,kwargs));raise MediaProcessError("Processo local excedeu o tempo limite.","timeout")
    adapter=Timeout()
    with pytest.raises(Exception) as raised:ChatterboxVoiceRenderer("timeout",adapter).render_batch([spec(),spec(order_index=1)])
    assert adapter.calls[0][1]["timeout"]==660 and raised.value.details["reasonCode"]=="BATCH_TIMEOUT"

def test_subtitle_segmentation_srt_ass_and_safe_area(tmp_path):
    text="Parafusadeira doméstica. Segunda frase também é legível e determinística.";assert len(blocks(text))==2;timed=cues(text,6);assert timed[0][0]==settings.subtitle_lead_in_seconds and timed[-1][1]==6
    files=SubtitleRenderer().write(text,6,tmp_path,"scene",540,960);assert "00:00:00,050 -->" in files["srt"].read_text(encoding="utf-8");ass=files["ass"].read_text(encoding="utf-8");assert "PlayResX: 540" in ass and "Style: Normal" in ass and str(int(960*settings.media_safe_margin_ratio)) in ass
    assert "Parafusadeira doméstica" in ass and "Parafusadeira doméstica".encode("utf-8") in files["ass"].read_bytes()

def test_scene_subtitle_single_window_uses_exact_audio_bounds(tmp_path):
    files=SubtitleRenderer().write("Uma frase. Outra frase.",3.742,tmp_path,"single",540,960,single_window=True);srt=files["srt"].read_text(encoding="utf-8");assert srt.count(" --> ")==1 and "00:00:00,000 --> 00:00:03,742" in srt

def test_subtitle_cues_use_real_wav_duration_punctuation_and_never_overlap():
    items=cues("Primeira parte, com detalhe. Última frase!",4.82,lead_in=.05);assert len(items)==3 and items[0][0]==.05 and items[-1][1]==4.82
    assert all(start<end<=4.82 for start,end,_ in items) and all(items[i][1]==items[i+1][0] for i in range(len(items)-1));assert cue_weight("Fim.")>cue_weight("Fim,")

@pytest.mark.parametrize("text",["Segmento único.","Primeiro trecho, segundo trecho. Último segmento!"])
def test_final_scene_last_subtitle_ends_at_audio_duration_without_gap(text):
    audio_duration=4.36025;items=cues(text,audio_duration);assert items[-1][1]==audio_duration and items[-1][1]<=audio_duration
    assert all(items[i][1]==items[i+1][0] for i in range(len(items)-1));assert timestamp(items[-1][1])=="00:00:04,360" and timestamp(items[-1][1],True)=="0:00:04.36"

def test_cumulative_scene_timing_uses_resolved_audio_durations_and_gaps():
    durations=[4.82,6.10];gap=.6;starts=[0,durations[0]+gap];ends=[starts[0]+durations[0],starts[1]+durations[1]];assert starts==[0,5.42] and ends==[4.82,11.52] and ends[0]<=starts[1]

def test_scene_renderer_generates_safe_ffmpeg_args(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));adapter=Adapter()
    with SessionLocal() as db:result=LocalSceneRenderer(db,"job",adapter).render(spec(),None,540,960)
    args=adapter.calls[-1][0];assert isinstance(args,list) and "libx264" in args and "aac" in args and result["path"].is_file();assert "não executar" not in args

@pytest.mark.parametrize("with_asset",[False,True])
def test_scene_renderer_escapes_ass_path_in_windows_filtergraph(tmp_path,monkeypatch,with_asset):
    monkeypatch.setattr(settings,"media_root",r"C:\Users\operator\affiliate-engine\data\media")
    adapter=Adapter();scene=spec()
    class Subtitle:
        def write(self,*args,**kwargs):return {"ass":Path(r"C:\Users\operator\affiliate-engine\data\media\jobs\abc\subtitles\scene_001.ass")}
    asset_file=tmp_path/"asset.png";asset_file.write_bytes(b"asset")
    asset=SimpleNamespace(relative_path="asset.png") if with_asset else None
    class DB:
        def get(self,*args):return asset
    monkeypatch.setattr(MediaStorage,"resolve",lambda self,path:asset_file if str(path)=="asset.png" else tmp_path/str(path).replace("/","_"))
    renderer=LocalSceneRenderer(DB(),"abc",adapter);renderer.subtitle=Subtitle()
    if with_asset:scene=spec(product_asset_ids=["asset"])
    renderer.render(scene,None,540,960)
    args=adapter.calls[-1][0];option="-filter_complex" if with_asset else "-vf";filter_value=args[args.index(option)+1]
    assert "ass=C:/Users/" not in filter_value
    assert r"ass='C\:/Users/operator/affiliate-engine/data/media/jobs/abc/subtitles/scene_001.ass'" in filter_value

def test_composer_order_atomic_finalize_and_profile_path(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"media_root",str(tmp_path));job=MediaJob(id="12345678-job",creative_id="c",render_type="PREVIEW",status="COMPOSING",width=540,height=960,fps=30,video_codec="h264",audio_codec="aac",progress_percent=80);adapter=Adapter();composer=LocalTimelineComposer(job,"Parafusadeira doméstica",adapter);a=tmp_path/"a.mp4";b=tmp_path/"b.mp4";a.write_bytes(b"a");b.write_bytes(b"b");output=composer.compose([{"path":a,"durationSeconds":1},{"path":b,"durationSeconds":2}],540,960,30);listing=(tmp_path/"jobs/12345678-job/concat.txt").read_text();assert listing.index("a.mp4")<listing.index("b.mp4") and output["tempPath"].name=="final.tmp.mp4";final=composer.finalize(output);assert final.name=="parafusadeira-domestica_12345678.mp4" and final.exists() and not output["tempPath"].exists()

@pytest.mark.parametrize("data,status",[({"streams":[{"codec_type":"video","codec_name":"h264","width":540,"height":960},{"codec_type":"audio","codec_name":"aac"}],"format":{"duration":"3"}},"VALID"),({"streams":[],"format":{"duration":"0"}},"INVALID")])
def test_real_validator(data,status,tmp_path):
    path=tmp_path/"final.tmp.mp4";path.write_bytes(b"MP4");job=MediaJob(render_type="PREVIEW",width=540,height=960,fps=30,video_codec="h264",audio_codec="aac",progress_percent=95);assert LocalMediaValidator(job,Adapter(data)).validate({"tempPath":path})["status"]==status

def test_validator_rejects_audio_video_timeline_drift_above_tolerance(tmp_path):
    path=tmp_path/"final.tmp.mp4";path.write_bytes(b"MP4");job=MediaJob(render_type="PREVIEW",width=540,height=960,fps=30,video_codec="h264",audio_codec="aac",progress_percent=95)
    valid={"streams":[{"codec_type":"video","codec_name":"h264","width":540,"height":960},{"codec_type":"audio","codec_name":"aac","duration":"5.70"}],"format":{"duration":"5.74"}};result=LocalMediaValidator(job,Adapter(valid)).validate({"tempPath":path,"durationSeconds":5.742});assert result["status"]=="VALID" and result["details"]["timelineDriftMilliseconds"]==42
    drifted={"streams":[{"codec_type":"video","codec_name":"h264","width":540,"height":960},{"codec_type":"audio","codec_name":"aac","duration":"5.20"}],"format":{"duration":"5.90"}};result=LocalMediaValidator(job,Adapter(drifted)).validate({"tempPath":path,"durationSeconds":5.742});assert result["status"]=="INVALID" and "TIMELINE_DRIFT_EXCEEDED" in result["details"]["reasons"]

def test_safe_slug_never_becomes_path():assert safe_slug("../../Parafusadeira doméstica & promoção") == "parafusadeira-domestica-promocao"
