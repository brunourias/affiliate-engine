import json,logging,os,re,shutil,sys,time,unicodedata
from pathlib import Path
from sqlalchemy.orm import Session
from apps.api.app.core.config import settings
from apps.api.app.db.models import CreativeScene,MediaAsset,MediaJob
from apps.api.app.services.ffmpeg_adapter import FFmpegAdapter,MediaProcessError,escape_filtergraph_path
from apps.api.app.services.media_pipeline import PipelineError,SceneRenderSpec
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.subtitle_renderer import SubtitleRenderer
from apps.api.app.services.voice_engine import CHATTERBOX_RUNNER,TTSNormalizer,chatterbox_probe,chatterbox_profile,resolve_local_reference
from apps.api.app.services.brand_assets import layout_boxes

logger=logging.getLogger(__name__)

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
class ChatterboxVoiceRenderer:
    def __init__(self,job_id,adapter=None,normalizer=None):self.job_id=job_id;self.adapter=adapter or FFmpegAdapter();self.normalizer=normalizer or TTSNormalizer();self.root=MediaStorage().resolve(f"jobs/{job_id}/audio");self.root.mkdir(parents=True,exist_ok=True)
    def render(self,spec):return self.render_batch([spec])[0]
    def render_batch(self,specs):
        narrated=[spec for spec in specs if spec.speaker!="NONE" and spec.narration_text]
        if not narrated:return [None for _ in specs]
        python=settings.chatterbox_python_path
        if not python or not Path(python).is_file():raise PipelineError("VOICE_RENDER_FAILED","Python isolado do Chatterbox não configurado.",{"provider":"CHATTERBOX","reasonCode":"PYTHON_NOT_CONFIGURED"})
        if not CHATTERBOX_RUNNER.is_file():raise PipelineError("VOICE_RENDER_FAILED","Runner local do Chatterbox não encontrado.",{"provider":"CHATTERBOX","reasonCode":"RUNNER_NOT_FOUND"})
        items=[]
        try:
            raw_root=self.root/"raw";raw_root.mkdir(exist_ok=True)
            for spec in narrated:
                profile=chatterbox_profile(spec.speaker);reference=resolve_local_reference(profile["reference"]);output=self.root/f"scene_{spec.order_index+1:03}.wav";raw=raw_root/output.name;normalized=self.normalizer.normalize(spec.narration_text)
                items.append({"sceneId":spec.scene_id,"sceneIndex":spec.order_index,"originalText":spec.narration_text,"text":normalized,"output":str(raw),"finalOutput":str(output),"language":settings.chatterbox_language,"exaggeration":profile["exaggeration"],"cfgWeight":profile["cfgWeight"],"reference":str(reference) if reference else None})
        except ValueError as exc:raise PipelineError("VOICE_RENDER_FAILED","Reference audio local inválido.",{"provider":"CHATTERBOX","reasonCode":"REFERENCE_AUDIO_INVALID"}) from exc
        timeout=settings.chatterbox_model_load_timeout_seconds+settings.chatterbox_synthesis_timeout_seconds*len(items);started=time.perf_counter()
        try:completed=self.adapter.run([python,str(CHATTERBOX_RUNNER),"--batch"],input_text=json.dumps({"items":items},ensure_ascii=False),timeout=timeout)
        except MediaProcessError as exc:
            reason="BATCH_TIMEOUT" if "tempo limite" in str(exc).lower() else "SYNTHESIS_FAILED"
            logger.warning("Chatterbox batch failed provider=CHATTERBOX reason=%s stderr=%s",reason,exc.sanitized_stderr or "unavailable")
            raise PipelineError("VOICE_RENDER_FAILED","Não foi possível gerar a voz da cena.",{"provider":"CHATTERBOX","reasonCode":reason,"totalDuration":round(time.perf_counter()-started,3)}) from exc
        marker="AFFILIATE_RESULT=";line=next((x[len(marker):] for x in reversed((completed.stdout or "").splitlines()) if x.startswith(marker)),None)
        try:metrics=json.loads(line) if line else None
        except json.JSONDecodeError:metrics=None
        if not metrics:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível validar o resultado da síntese.",{"provider":"CHATTERBOX","reasonCode":"RUNNER_RESULT_INVALID"})
        process_duration=time.perf_counter()-started
        self.last_metrics={"provider":"CHATTERBOX","startupDuration":round(max(0,process_duration-float(metrics.get("totalDuration") or process_duration)),3),"importDuration":metrics.get("importDuration"),"modelLoadDuration":metrics.get("modelLoadDuration"),"synthesisDuration":metrics.get("synthesisDuration"),"totalDuration":round(process_duration,3),"sceneCount":len(items)}
        by_index={}
        for item in items:
            raw=Path(item["output"]);output=Path(item["finalOutput"])
            if not raw.exists() or raw.stat().st_size==0:raise PipelineError("VOICE_RENDER_FAILED","A voz local não gerou um WAV válido.",{"provider":"CHATTERBOX","reasonCode":"WAV_INVALID"})
            try:
                if settings.chatterbox_trim_silence_enabled:self.adapter.trim_audio_edges(raw,output,settings.chatterbox_trim_silence_threshold_db,settings.chatterbox_trim_silence_duration_seconds,settings.chatterbox_trim_silence_padding_seconds)
                else:shutil.copy2(raw,output)
            except MediaProcessError as exc:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível finalizar o áudio da cena.",{"provider":"CHATTERBOX","reasonCode":"WAV_POST_PROCESS_FAILED"}) from exc
            try:duration=self.adapter.audio_duration(output)
            except (MediaProcessError,ValueError) as exc:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível validar o áudio da cena.",{"provider":"CHATTERBOX","reasonCode":"WAV_VALIDATION_FAILED"}) from exc
            if duration<=0:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível validar o áudio da cena.",{"provider":"CHATTERBOX","reasonCode":"WAV_DURATION_INVALID"})
            logger.info("Chatterbox scene=%s original=%r normalized=%r duration=%.3f",item["sceneIndex"],item["originalText"],item["text"],duration)
            by_index[item["sceneId"]]={"path":output,"durationSeconds":duration}
        return [by_index.get(spec.scene_id) for spec in specs]
class LocalSceneRenderer:
    def __init__(self,db:Session,job_id,adapter=None):self.db=db;self.job_id=job_id;self.adapter=adapter or FFmpegAdapter();self.root=MediaStorage().resolve(f"jobs/{job_id}");self.scenes=self.root/"scenes";self.subtitles=self.root/"subtitles";self.scenes.mkdir(parents=True,exist_ok=True);self.subtitle=SubtitleRenderer()
    def render(self,spec,audio,width,height):
        output=self.scenes/f"scene_{spec.order_index+1:03}.mp4";duration=spec.resolved_duration_seconds;text=spec.on_screen_text or spec.narration_text or ""
        if spec.disclosure_text:text=(text+"\n"+spec.disclosure_text).strip()
        spoken_duration=float(audio["durationSeconds"]) if audio else duration
        ass=self.subtitle.write(text,spoken_duration,self.subtitles,f"scene_{spec.order_index+1:03}",width,height,single_window=bool(audio))["ass"]
        args=["-f","lavfi","-i",f"color=c={settings.media_background_color}:s={width}x{height}:r=30:d={duration:.3f}"]
        visual_inputs=[];allowed_roles={"PRODUCT":{"product"},"AVATAR":{"avatar"},"TEXT":{"product"},"BRAND_FALLBACK":{"product"},"MIXED":{"product","avatar"},"WARNING":{"product","avatar"},"CTA":{"product","avatar"}}.get(spec.layout_type,set())
        for role,asset_id in (("product",spec.product_asset_ids[0] if spec.product_asset_ids else None),("avatar",spec.avatar_asset_id)):
            if role not in allowed_roles:continue
            asset=self.db.get(MediaAsset,asset_id) if asset_id else None;path=MediaStorage().resolve(asset.relative_path) if asset else None
            if path and path.exists():args += ["-loop","1","-i",str(path)];visual_inputs.append((role,len(visual_inputs)+1))
        audio_index=1+len(visual_inputs)
        if audio:args += ["-i",str(audio["path"])]
        else:args += ["-f","lavfi","-i",f"anullsrc=r=48000:cl=stereo:d={duration:.3f}"]
        ass_filter_path=escape_filtergraph_path(ass)
        if visual_inputs:
            boxes=layout_boxes(width,height,spec.layout_type);filters=[];current="0:v"
            if spec.layout_type=="WARNING":filters.append(f"[{current}]drawbox=x={round(width*.06)}:y={round(height*.06)}:w={round(width*.88)}:h={round(height*.015)}:color=#D39B3A@0.85:t=fill[base]");current="base"
            for position,(role,index) in enumerate(visual_inputs):
                box=boxes[role];asset_label=f"asset{position}";next_label=f"layer{position}"
                filters.append(f"[{index}:v]format=rgba,scale={box.width}:{box.height}:force_original_aspect_ratio=decrease[{asset_label}]")
                filters.append(f"[{current}][{asset_label}]overlay=x={box.x}+({box.width}-w)/2:y={box.y}+({box.height}-h)/2:format=auto[{next_label}]");current=next_label
            filters.append(f"[{current}]ass={ass_filter_path}[v]");args += ["-filter_complex",";".join(filters),"-map","[v]","-map",f"{audio_index}:a:0"]
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
        duration=float(data.get("format",{}).get("duration") or 0);timeline=float(output.get("durationSeconds") if output.get("durationSeconds") is not None else duration);audio_duration=float((audio or {}).get("duration") or duration);drift=max(abs(duration-timeline),abs(audio_duration-timeline),abs(duration-audio_duration));tolerance=settings.media_timeline_drift_tolerance_seconds
        if duration<=0:reasons.append("DURATION_INVALID")
        if drift>tolerance:reasons.append("TIMELINE_DRIFT_EXCEEDED")
        return {"status":"INVALID" if reasons else "VALID","details":{"reasons":reasons,"durationSeconds":duration,"audioTimelineDuration":timeline,"audioDurationSeconds":audio_duration,"videoDurationSeconds":duration,"timelineDriftMilliseconds":round(drift*1000),"driftToleranceMilliseconds":round(tolerance*1000),"sizeBytes":path.stat().st_size}}
def voice_renderer(job_id,adapter=None):
    provider=settings.tts_provider.upper()
    if provider=="PIPER":return PiperVoiceRenderer(job_id,adapter)
    if provider=="CHATTERBOX":return ChatterboxVoiceRenderer(job_id,adapter)
    raise PipelineError("VOICE_RENDER_FAILED","Provider de voz local não configurado.")
def local_adapters(db,job,creative):
    adapter=FFmpegAdapter();return voice_renderer(job.id,adapter),LocalSceneRenderer(db,job.id,adapter),LocalTimelineComposer(job,creative.title or creative.name,adapter),LocalMediaValidator(job,adapter)
def local_preflight(db,job):
    adapter=FFmpegAdapter()
    try:adapter.version(adapter.ffmpeg);adapter.version(adapter.ffprobe)
    except MediaProcessError:return "FFmpeg/FFprobe não configurados."
    scenes=db.query(CreativeScene).filter_by(creative_id=job.creative_id).all();speakers={x.speaker for x in scenes if x.narration_text and x.speaker!="NONE"}
    if speakers:
        provider=settings.tts_provider.upper()
        if provider=="PIPER":
            renderer=PiperVoiceRenderer(job.id,adapter);command=renderer.command()
            if not command[0] or (not Path(command[0]).is_file() and not shutil.which(command[0])):return "Executável de voz local não encontrado."
            if any(not renderer.model(x) or not Path(renderer.model(x)).is_file() or not Path(renderer.model_config(x)).is_file() for x in speakers):return "Perfil de voz local não configurado para todas as cenas."
        elif provider=="CHATTERBOX":
            if not settings.chatterbox_python_path or not Path(settings.chatterbox_python_path).is_file() or not CHATTERBOX_RUNNER.is_file():return "Chatterbox local não configurado."
            if chatterbox_probe(settings.chatterbox_python_path)[0]!="AVAILABLE":return "Chatterbox local indisponível."
            try:
                for speaker in speakers:resolve_local_reference(chatterbox_profile(speaker)["reference"])
            except ValueError:return "Reference audio local inválido."
        else:return "Provider de voz local não configurado."
    return None
