import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from apps.api.app.core.config import settings
from apps.api.app.services.ffmpeg_adapter import FFmpegAdapter,MediaProcessError,escape_filtergraph_path
from apps.api.app.services.local_media import LocalMediaValidator,LocalSceneRenderer,LocalTimelineComposer,PiperVoiceRenderer,safe_slug
from apps.api.app.services.media_pipeline import SceneRenderSpec
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.subtitle_renderer import SubtitleRenderer,blocks,cues
from apps.api.app.db.models import MediaJob
from apps.api.app.db.session import SessionLocal

class Adapter:
    def __init__(self,probe=None):self.calls=[];self.data=probe or {"streams":[{"codec_type":"video","codec_name":"h264","width":540,"height":960},{"codec_type":"audio","codec_name":"aac"}],"format":{"duration":"3.2"}}
    def run(self,args,**kwargs):
        self.calls.append((args,kwargs));Path(args[args.index("--output_file")+1]).write_bytes(b"WAV") if "--output_file" in args else None;return subprocess.CompletedProcess(args,0,"piper 1","")
    def audio_duration(self,path):return 3.2
    def render_scene(self,args):self.calls.append((args,{}));Path(args[-1]).write_bytes(b"MP4")
    def compose(self,args):self.calls.append((args,{}));Path(args[-1]).write_bytes(b"MP4")
    def probe(self,path):return self.data

def spec(**changes):
    values=dict(scene_id="s1",order_index=0,scene_type="TEXT",speaker="NARRATOR",narration_text="Texto seguro -- sem execução",on_screen_text="Na tela",visual_instruction="não executar",avatar_state=None,requested_duration_seconds=2,resolved_duration_seconds=3.8,product_asset_ids=[],avatar_asset_id=None,disclosure_text=None,required_warning_codes=[],layout_type="TEXT");values.update(changes);return SceneRenderSpec(**values)

def test_ffmpeg_adapter_uses_argument_list_and_shell_false(monkeypatch):
    seen={}
    def run(args,**kwargs):seen.update(kwargs);assert isinstance(args,list);return subprocess.CompletedProcess(args,0,"ffmpeg version test\n","")
    monkeypatch.setattr(subprocess,"run",run);assert FFmpegAdapter().version("ffmpeg")=="ffmpeg version test" and seen["shell"] is False

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

def test_subtitle_segmentation_srt_ass_and_safe_area(tmp_path):
    text="Parafusadeira doméstica. Segunda frase também é legível e determinística.";assert len(blocks(text))==2;timed=cues(text,6);assert timed[0][0]==0 and timed[-1][1]==6
    files=SubtitleRenderer().write(text,6,tmp_path,"scene",540,960);assert "00:00:00,000 -->" in files["srt"].read_text(encoding="utf-8");ass=files["ass"].read_text(encoding="utf-8");assert "PlayResX: 540" in ass and "Style: Normal" in ass and str(int(960*settings.media_safe_margin_ratio)) in ass
    assert "Parafusadeira doméstica" in ass and "Parafusadeira doméstica".encode("utf-8") in files["ass"].read_bytes()

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

def test_safe_slug_never_becomes_path():assert safe_slug("../../Parafusadeira doméstica & promoção") == "parafusadeira-domestica-promocao"
