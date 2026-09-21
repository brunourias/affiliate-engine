import os,re,shutil,sys,unicodedata
from pathlib import Path
from sqlalchemy.orm import Session
from apps.api.app.core.config import settings
from apps.api.app.db.models import CreativeScene,MediaAsset,MediaJob
from apps.api.app.services.ffmpeg_adapter import FFmpegAdapter,MediaProcessError,escape_filtergraph_path
from apps.api.app.services.media_pipeline import PipelineError,SceneRenderSpec
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.subtitle_renderer import SubtitleRenderer

def safe_slug(value):
    value=unicodedata.normalize("NFKD",value).encode("ascii","ignore").decode().lower();value=re.sub(r"[^a-z0-9]+","-",value).strip("-");return (value[:60] or "video")
class PiperVoiceRenderer:
    def __init__(self,job_id,adapter=None):self.job_id=job_id;self.adapter=adapter or FFmpegAdapter();self.root=MediaStorage().resolve(f"jobs/{job_id}/audio");self.root.mkdir(parents=True,exist_ok=True)
    def model(self,speaker):return {"BRUNO":settings.tts_model_bruno,"CAROL":settings.tts_model_carol,"NARRATOR":settings.tts_model_narrator}.get(speaker,"")
    def model_config(self,speaker):
        configured={"BRUNO":settings.tts_model_config_bruno,"CAROL":settings.tts_model_config_carol,"NARRATOR":settings.tts_model_config_narrator}.get(speaker,"");model=self.model(speaker);return configured or (str(Path(model).with_suffix(Path(model).suffix+".json")) if model else "")
    def command(self):
        if settings.tts_invocation_mode.upper()=="MODULE":return [settings.tts_python_path or sys.executable,"-m",settings.tts_python_module]
        return [settings.tts_executable_path]
    def render(self,spec):
        model=self.model(spec.speaker)
        if spec.speaker=="NONE" or not spec.narration_text:return None
        config=self.model_config(spec.speaker)
        if not model:raise PipelineError("VOICE_RENDER_FAILED","Modelo de voz local não configurado.")
        if not Path(model).is_file():raise PipelineError("VOICE_RENDER_FAILED","Modelo de voz local não encontrado.")
        if not config or not Path(config).is_file():raise PipelineError("VOICE_RENDER_FAILED","Configuração do modelo de voz não encontrada.")
        command=self.command()
        if not command[0] or (not Path(command[0]).is_file() and not shutil.which(command[0])):raise PipelineError("VOICE_RENDER_FAILED","Executável de voz local não encontrado.")
        output=self.root/f"scene_{spec.order_index+1:03}.wav"
        try:self.adapter.run([*command,"--model",model,"--config",config,"--output_file",str(output)],input_text=spec.narration_text,timeout=settings.media_subprocess_timeout_seconds)
        except MediaProcessError as exc:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível gerar a voz da cena.") from exc
        if not output.exists() or output.stat().st_size==0:raise PipelineError("VOICE_RENDER_FAILED","A voz local não gerou um WAV válido.")
        try:duration=self.adapter.audio_duration(output)
        except (MediaProcessError,ValueError) as exc:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível validar o áudio da cena.") from exc
        return {"path":output,"durationSeconds":duration}
class LocalSceneRenderer:
    def __init__(self,db:Session,job_id,adapter=None):self.db=db;self.job_id=job_id;self.adapter=adapter or FFmpegAdapter();self.root=MediaStorage().resolve(f"jobs/{job_id}");self.scenes=self.root/"scenes";self.subtitles=self.root/"subtitles";self.scenes.mkdir(parents=True,exist_ok=True);self.subtitle=SubtitleRenderer()
    def render(self,spec,audio,width,height):
        output=self.scenes/f"scene_{spec.order_index+1:03}.mp4";duration=spec.resolved_duration_seconds;text=spec.on_screen_text or spec.narration_text or ""
        if spec.disclosure_text:text=(text+"\n"+spec.disclosure_text).strip()
        ass=self.subtitle.write(text,duration,self.subtitles,f"scene_{spec.order_index+1:03}",width,height)["ass"]
        args=["-f","lavfi","-i",f"color=c={settings.media_background_color}:s={width}x{height}:r=30:d={duration:.3f}"];asset_id=spec.avatar_asset_id or (spec.product_asset_ids[0] if spec.product_asset_ids else None);asset=self.db.get(MediaAsset,asset_id) if asset_id else None;asset_path=MediaStorage().resolve(asset.relative_path) if asset else None
        if asset_path and asset_path.exists():args += ["-loop","1","-i",str(asset_path)]
        audio_index=2 if asset_path and asset_path.exists() else 1
        if audio:args += ["-i",str(audio["path"])]
        else:args += ["-f","lavfi","-i",f"anullsrc=r=48000:cl=stereo:d={duration:.3f}"]
        ass_filter_path=escape_filtergraph_path(ass)
        if audio_index==2:
            graph=f"[1:v]scale={round(width*.78)}:{round(height*.55)}:force_original_aspect_ratio=decrease[asset];[0:v][asset]overlay=(W-w)/2:(H-h)/2,ass={ass_filter_path}[v]";args += ["-filter_complex",graph,"-map","[v]","-map",f"{audio_index}:a:0"]
        else:args += ["-vf",f"ass={ass_filter_path}","-map","0:v:0","-map",f"{audio_index}:a:0"]
        args += ["-t",f"{duration:.3f}","-c:v","libx264","-pix_fmt","yuv420p","-r","30","-c:a","aac","-ar","48000","-movflags","+faststart",str(output)]
        try:self.adapter.render_scene(args)
        except MediaProcessError as exc:raise PipelineError("SCENE_RENDER_FAILED",f"Não foi possível renderizar a cena {spec.order_index+1}.") from exc
        if not output.exists() or output.stat().st_size==0:raise PipelineError("SCENE_RENDER_FAILED",f"A cena {spec.order_index+1} não gerou arquivo válido.")
        return {"path":output,"artifactId":output.name,"sceneIndex":spec.order_index,"durationSeconds":duration,"width":width,"height":height}
class LocalTimelineComposer:
    def __init__(self,job:MediaJob,title:str,adapter=None):self.job=job;self.adapter=adapter or FFmpegAdapter();self.root=MediaStorage().resolve(f"jobs/{job.id}");self.root.mkdir(parents=True,exist_ok=True);self.title=title
    def compose(self,scenes,width,height,fps):
        if not scenes:raise PipelineError("COMPOSE_FAILED","O criativo não possui cenas para compor.")
        listing=self.root/"concat.txt";listing.write_text("\n".join("file '"+Path(x["path"]).resolve().as_posix().replace("'","'\\''")+"'" for x in scenes),encoding="utf-8");temp=self.root/"final.tmp.mp4";final_dir=self.root/("preview" if self.job.render_type=="PREVIEW" else "final");final_dir.mkdir(exist_ok=True);final=final_dir/f"{safe_slug(self.title)}_{self.job.id[:8]}.mp4"
        args=["-f","concat","-safe","0","-i",str(listing),"-c:v","libx264","-pix_fmt","yuv420p","-r",str(fps),"-c:a","aac","-ar","48000","-movflags","+faststart",str(temp)]
        try:self.adapter.compose(args)
        except MediaProcessError as exc:raise PipelineError("COMPOSE_FAILED","Não foi possível finalizar o vídeo.") from exc
        return {"tempPath":temp,"finalPath":final,"durationSeconds":sum(x["durationSeconds"] for x in scenes),"width":width,"height":height,"fps":fps}
    def finalize(self,output):os.replace(output["tempPath"],output["finalPath"]);return output["finalPath"]
class LocalMediaValidator:
    def __init__(self,job:MediaJob,adapter=None):self.job=job;self.adapter=adapter or FFmpegAdapter()
    def validate(self,output):
        path=Path(output["tempPath"])
        if not path.exists() or path.stat().st_size==0:return {"status":"INVALID","details":{"reason":"EMPTY_FILE"}}
        try:data=self.adapter.probe(path)
        except (MediaProcessError,ValueError):return {"status":"INVALID","details":{"reason":"FFPROBE_FAILED"}}
        streams=data.get("streams",[]);video=next((x for x in streams if x.get("codec_type")=="video"),None);audio=next((x for x in streams if x.get("codec_type")=="audio"),None);reasons=[]
        if not video or video.get("codec_name")!="h264" or video.get("width")!=self.job.width or video.get("height")!=self.job.height:reasons.append("VIDEO_STREAM_INVALID")
        if not audio or audio.get("codec_name")!="aac":reasons.append("AUDIO_STREAM_INVALID")
        duration=float(data.get("format",{}).get("duration") or 0)
        if duration<=0:reasons.append("DURATION_INVALID")
        return {"status":"INVALID" if reasons else "VALID","details":{"reasons":reasons,"durationSeconds":duration,"sizeBytes":path.stat().st_size}}
def local_adapters(db,job,creative):
    adapter=FFmpegAdapter();return PiperVoiceRenderer(job.id,adapter),LocalSceneRenderer(db,job.id,adapter),LocalTimelineComposer(job,creative.title or creative.name,adapter),LocalMediaValidator(job,adapter)
def local_preflight(db,job):
    adapter=FFmpegAdapter()
    try:adapter.version(adapter.ffmpeg);adapter.version(adapter.ffprobe)
    except MediaProcessError:return "FFmpeg/FFprobe não configurados."
    scenes=db.query(CreativeScene).filter_by(creative_id=job.creative_id).all();speakers={x.speaker for x in scenes if x.narration_text and x.speaker!="NONE"}
    if speakers:
        if settings.tts_provider!="PIPER":return "Piper/TTS local não configurado."
        renderer=PiperVoiceRenderer(job.id,adapter)
        command=renderer.command()
        if not command[0] or (not Path(command[0]).is_file() and not shutil.which(command[0])):return "Executável de voz local não encontrado."
        if any(not renderer.model(x) or not Path(renderer.model(x)).is_file() or not Path(renderer.model_config(x)).is_file() for x in speakers):return "Perfil de voz local não configurado para todas as cenas."
    return None
