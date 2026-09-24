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
from apps.api.app.services.motion import avatar_filter,overlay_position,product_scale_filter,select_motion
from apps.api.app.services.voice_director import FINAL_TIMING_PACE_ADJUSTMENT,direction_for_purpose,final_timing_speed,provider_parameters
from apps.api.app.services.shot_director import ShotDirector,visual_checks
from apps.api.app.services.voice_synthesis_guard import VoiceSynthesisGuard,conservative_parameters
from apps.api.app.services.commercial_polish import commercial_checks,polish_headline,polish_shots
from apps.api.app.services.product_media import BrollDirector,ProductMediaAnalyzer,repetition_metrics

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
                profile=chatterbox_profile(spec.speaker);direction=direction_for_purpose(spec.purpose);parameters=provider_parameters(direction,profile);reference=resolve_local_reference(profile["reference"]);output=self.root/f"scene_{spec.order_index+1:03}.wav";raw=raw_root/output.name;normalized=self.normalizer.normalize(spec.narration_text)
                items.append({"sceneId":spec.scene_id,"sceneIndex":spec.order_index,"originalText":spec.narration_text,"text":normalized,"output":str(raw),"finalOutput":str(output),"language":settings.chatterbox_language,"exaggeration":parameters["exaggeration"],"cfgWeight":parameters["cfgWeight"],"reference":str(reference) if reference else None,"direction":direction,"speaker":spec.speaker})
        except ValueError as exc:raise PipelineError("VOICE_RENDER_FAILED","Reference audio local inválido.",{"provider":"CHATTERBOX","reasonCode":"REFERENCE_AUDIO_INVALID"}) from exc
        timeout=settings.chatterbox_model_load_timeout_seconds+settings.chatterbox_synthesis_timeout_seconds*len(items);started=time.perf_counter()
        runner_items=[{key:value for key,value in item.items() if key!="direction"} for item in items]
        try:completed=self.adapter.run([python,str(CHATTERBOX_RUNNER),"--batch"],input_text=json.dumps({"items":runner_items},ensure_ascii=False),timeout=timeout)
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
        by_index={};self.synthesis_events=[];guard=VoiceSynthesisGuard()
        for item in items:
            output=Path(item["finalOutput"]);direction=item["direction"];attempts=[];selected=None
            for attempt in range(1,4):
                raw=Path(item["output"]) if attempt==1 else Path(item["output"]).with_name(Path(item["output"]).stem+f"_attempt_{attempt}.wav");trimmed=raw.with_name(raw.stem+"_trimmed.wav");parameters={"exaggeration":item["exaggeration"],"cfgWeight":item["cfgWeight"]} if attempt<3 else conservative_parameters(item)
                if attempt>1:
                    retry={key:value for key,value in item.items() if key not in {"direction","speaker","finalOutput","originalText"}};retry.update({"output":str(raw),**parameters})
                    try:self.adapter.run([python,str(CHATTERBOX_RUNNER),"--batch"],input_text=json.dumps({"items":[retry]},ensure_ascii=False),timeout=settings.chatterbox_model_load_timeout_seconds+settings.chatterbox_synthesis_timeout_seconds)
                    except MediaProcessError as exc:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível regenerar a voz da cena.",{"provider":"CHATTERBOX","reasonCode":"SYNTHESIS_FAILED","sceneId":item["sceneId"],"sceneIndex":item["sceneIndex"],"attempt":attempt}) from exc
                if not raw.exists() or raw.stat().st_size==0:raise PipelineError("VOICE_RENDER_FAILED","A voz local não gerou um WAV válido.",{"provider":"CHATTERBOX","reasonCode":"WAV_INVALID"})
                try:
                    raw_duration=self.adapter.audio_duration(raw);silence=self.adapter.silence_edges(raw,settings.chatterbox_trim_silence_threshold_db,settings.chatterbox_trim_silence_duration_seconds,raw_duration) if hasattr(self.adapter,"silence_edges") else {"leadingSilenceSeconds":0.0,"trailingSilenceSeconds":0.0}
                    if settings.chatterbox_trim_silence_enabled:self.adapter.trim_audio_edges(raw,trimmed,settings.chatterbox_trim_silence_threshold_db,settings.chatterbox_trim_silence_duration_seconds,settings.chatterbox_trim_silence_padding_seconds)
                    else:shutil.copy2(raw,trimmed)
                    trimmed_duration=self.adapter.audio_duration(trimmed)
                except MediaProcessError as exc:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível finalizar o áudio da cena.",{"provider":"CHATTERBOX","reasonCode":"WAV_POST_PROCESS_FAILED"}) from exc
                validation=guard.validate(item["text"],trimmed_duration,silence["leadingSilenceSeconds"],silence["trailingSilenceSeconds"]);event={"sceneId":item["sceneId"],"sceneIndex":item["sceneIndex"],"speaker":item["speaker"],"voiceStyle":direction.voice_style,"attempt":attempt,"rawDuration":round(raw_duration,3),"trimmedDuration":round(trimmed_duration,3),"finalDuration":None,**validation.metadata()};attempts.append(event);self.synthesis_events.append(event)
                if validation.status=="VALID":selected=(trimmed,raw_duration,trimmed_duration,silence,parameters,event);break
            if not selected:raise PipelineError("VOICE_SYNTHESIS_OUTLIER",f"Síntese de voz anormal na cena {item['sceneIndex']+1} após 3 tentativas.",{"provider":"CHATTERBOX","reasonCode":"DURATION_OUTLIER","sceneId":item["sceneId"],"sceneIndex":item["sceneIndex"],"attempts":attempts})
            trimmed,raw_duration,trimmed_duration,silence,parameters,event=selected
            try:
                if hasattr(self.adapter,"direct_voice"):self.adapter.direct_voice(trimmed,output,final_timing_speed(direction),direction.pause_before_ms,direction.pause_after_ms)
                else:shutil.copy2(trimmed,output)
            except MediaProcessError as exc:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível finalizar o áudio da cena.",{"provider":"CHATTERBOX","reasonCode":"WAV_POST_PROCESS_FAILED"}) from exc
            try:duration=self.adapter.audio_duration(output)
            except (MediaProcessError,ValueError) as exc:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível validar o áudio da cena.",{"provider":"CHATTERBOX","reasonCode":"WAV_VALIDATION_FAILED"}) from exc
            if duration<=0:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível validar o áudio da cena.",{"provider":"CHATTERBOX","reasonCode":"WAV_DURATION_INVALID"})
            logger.info("Chatterbox scene=%s original=%r normalized=%r duration=%.3f",item["sceneIndex"],item["originalText"],item["text"],duration)
            event["finalDuration"]=round(duration,3);metadata={**direction.metadata(),"speed":final_timing_speed(direction),"timingPaceAdjustment":FINAL_TIMING_PACE_ADJUSTMENT,"speaker":item["speaker"],"exaggeration":parameters["exaggeration"],"cfgWeight":parameters["cfgWeight"],"rawDurationSeconds":round(raw_duration,3),"trimmedDurationSeconds":round(trimmed_duration,3),"finalDurationSeconds":round(duration,3),"synthesisAttempts":attempts,**silence}
            by_index[item["sceneId"]]={"path":output,"durationSeconds":duration,"voiceMetadata":metadata}
        return [by_index.get(spec.scene_id) for spec in specs]
class LocalSceneRenderer:
    def __init__(self,db:Session,job_id,adapter=None):self.db=db;self.job_id=job_id;self.adapter=adapter or FFmpegAdapter();self.root=MediaStorage().resolve(f"jobs/{job_id}");self.scenes=self.root/"scenes";self.subtitles=self.root/"subtitles";self.scenes.mkdir(parents=True,exist_ok=True);self.subtitle=SubtitleRenderer()
    def render(self,spec,audio,width,height):
        output=self.scenes/f"scene_{spec.order_index+1:03}.mp4";duration=spec.resolved_duration_seconds;text=spec.narration_text or ""
        if spec.disclosure_text:text=(text+"\n"+spec.disclosure_text).strip()
        spoken_duration=float(audio["durationSeconds"]) if audio else duration
        ass=self.subtitle.write(text,spoken_duration,self.subtitles,f"scene_{spec.order_index+1:03}",width,height,single_window=bool(audio))["ass"]
        args=["-f","lavfi","-i",f"color=c={settings.media_background_color}:s={width}x{height}:r=30:d={duration:.3f}"]
        visual_inputs=[];allowed_roles={"PRODUCT":{"product"},"AVATAR":{"avatar"},"TEXT":{"product"},"BRAND_FALLBACK":{"product"},"MIXED":{"product","avatar"},"WARNING":{"product","avatar"},"CTA":{"product","avatar"}}.get(spec.layout_type,set());product_id=spec.product_asset_ids[0] if spec.product_asset_ids else None
        headline,headline_adjusted,headline_status=polish_headline(spec.purpose,spec.on_screen_text,text);shots=ShotDirector().plan(spec.purpose,spec.visual_instruction,duration,bool(product_id),bool(spec.avatar_asset_id),headline);shots,shots_adjusted,visual_delta=polish_shots(shots,spec.purpose);shot_meta=[x.metadata(i) for i,x in enumerate(shots)]
        first_asset=self.db.get(MediaAsset,product_id) if product_id else None;owner_id=getattr(first_asset,"owner_id",None)
        if owner_id:bundle=ProductMediaAnalyzer().analyze(self.db,owner_id)
        elif first_asset:bundle={"assetCount":1,"uniqueVisualGroups":1,"assets":[{"assetId":product_id,"mediaType":getattr(first_asset,"asset_type","PRODUCT_IMAGE"),"classification":"UNKNOWN_PRODUCT_MEDIA","qualityScore":50,"duplicateGroup":"PRODUCT_MEDIA_01","warnings":[]}],"diversityLevel":"LOW","qualityCheck":"WARNING"}
        else:bundle={"assetCount":0,"uniqueVisualGroups":0,"assets":[],"diversityLevel":"LOW","qualityCheck":"WARNING"}
        assignments=BrollDirector().assign(shots,spec.purpose,bundle);repetition=repetition_metrics(assignments)
        shot_meta=[{**meta,"sourceAssetId":source["assetId"] if source else None,"sourceMediaType":source["mediaType"] if source else None,"sourceClassification":source["classification"] if source else None,"duplicateGroup":source["duplicateGroup"] if source else None} for meta,source in zip(shot_meta,assignments)]
        roles=[]
        if assignments and assignments[0] and "product" in allowed_roles:roles.append(("background",assignments[0]["assetId"],None))
        roles.extend((f"product:{index}",source["assetId"],index) for index,source in enumerate(assignments) if source);roles.append(("avatar",spec.avatar_asset_id if any(x.persona_visible for x in shots) else None,None))
        for role,asset_id,shot_index in roles:
            if role!="background" and not role.startswith("product:") and role not in allowed_roles:continue
            asset=self.db.get(MediaAsset,asset_id) if asset_id else None;path=MediaStorage().resolve(asset.relative_path) if asset else None
            if path and path.exists():args += (["-stream_loop","-1","-i",str(path)] if getattr(asset,"asset_type","PRODUCT_IMAGE")=="PRODUCT_VIDEO" else ["-loop","1","-i",str(path)]);visual_inputs.append((role,len(visual_inputs)+1,shot_index))
        audio_index=1+len(visual_inputs)
        if audio:args += ["-i",str(audio["path"])]
        else:args += ["-f","lavfi","-i",f"anullsrc=r=48000:cl=stereo:d={duration:.3f}"]
        ass_filter_path=escape_filtergraph_path(ass)
        motion=select_motion(spec.layout_type,spec.order_index,any(x[0].startswith("product:") for x in visual_inputs),any(x[0]=="avatar" for x in visual_inputs),width,height,spec.purpose)
        if visual_inputs:
            boxes=layout_boxes(width,height,spec.layout_type);filters=[];current="0:v"
            if spec.layout_type=="WARNING":filters.append(f"[{current}]drawbox=x={round(width*.06)}:y={round(height*.06)}:w={round(width*.88)}:h={round(height*.015)}:color=#D39B3A@0.85:t=fill[base]");current="base"
            for position,(role,index,shot_index) in enumerate(visual_inputs):
                asset_label=f"asset{position}";next_label=f"layer{position}"
                if role=="background":
                    filters.append(f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=20:2,eq=contrast=.78:brightness=-.05[{asset_label}]");filters.append(f"[{current}][{asset_label}]overlay=0:0:format=auto[{next_label}]")
                else:
                    product_role=role.startswith("product:");box=boxes["product" if product_role else role];filters.append(product_scale_filter(f"{index}:v",asset_label,box.width,box.height,duration,motion) if product_role else avatar_filter(f"{index}:v",asset_label,box.width,box.height,motion));x,y=overlay_position("product" if product_role else role,box,duration,motion)
                    if product_role and shot_index is not None:
                        shot=shots[shot_index];x=round(width*.04) if shot.anchor=="LEFT" else round(width*.18) if shot.anchor=="RIGHT" else x
                    enabled=""
                    if role=="avatar":
                        periods=[f"between(t\\,{x.start:.3f}\\,{x.end:.3f})" for x in shots if x.persona_visible];enabled=f":enable='{'+'.join(periods)}'" if periods else ""
                    elif product_role and shot_index is not None:
                        shot=shots[shot_index];enabled=f":enable='between(t\\,{shot.start:.3f}\\,{shot.end:.3f})'"
                    filters.append(f"[{current}][{asset_label}]overlay=x='{x}':y='{y}':format=auto{enabled}[{next_label}]")
                current=next_label
            enter=motion.enter_duration_ms/1000;exit_duration=min(motion.exit_duration_ms/1000,duration/2);exit_start=max(0,duration-exit_duration)
            filters.append(f"[{current}]fade=t=in:st=0:d={enter:.3f},fade=t=out:st={exit_start:.3f}:d={exit_duration:.3f}[transition]")
            headline_file=self.subtitle.write_headline(headline,duration,self.subtitles,f"scene_{spec.order_index+1:03}",width,height,shots[0].text_layout if shots else "TOP_BANNER") if headline and hasattr(self.subtitle,"write_headline") else None
            headline_filter=f",ass={escape_filtergraph_path(headline_file)}" if headline_file else "";filters.append(f"[transition]{headline_filter.lstrip(',')+',' if headline_filter else ''}ass={ass_filter_path}[v]");args += ["-filter_complex",";".join(filters),"-map","[v]","-map",f"{audio_index}:a:0"]
        else:
            enter=motion.enter_duration_ms/1000;exit_duration=min(motion.exit_duration_ms/1000,duration/2);exit_start=max(0,duration-exit_duration)
            args += ["-vf",f"fade=t=in:st=0:d={enter:.3f},fade=t=out:st={exit_start:.3f}:d={exit_duration:.3f},ass={ass_filter_path}","-map","0:v:0","-map",f"{audio_index}:a:0"]
        args += ["-t",f"{duration:.3f}","-c:v","libx264","-pix_fmt","yuv420p","-r","30","-c:a","aac","-ar","48000","-movflags","+faststart",str(output)]
        try:self.adapter.render_scene(args)
        except MediaProcessError as exc:raise PipelineError("SCENE_RENDER_FAILED",f"Não foi possível renderizar a cena {spec.order_index+1}.") from exc
        if not output.exists() or output.stat().st_size==0:raise PipelineError("SCENE_RENDER_FAILED",f"A cena {spec.order_index+1} não gerou arquivo válido.")
        checks=visual_checks(shots,duration,spec.purpose);commercial=commercial_checks(shots,headline_status,{"gapsOver250Ms":0},spec.purpose);media_checks={"MEDIA_DIVERSITY":bundle.get("qualityCheck","WARNING"),"SOURCE_ASSET_REPETITION":"PASS" if repetition["uniqueSourceAssets"]>=3 and repetition["percentageUsingMostCommonAsset"]<=60 else "WARNING","BROLL_RELEVANCE":"PASS" if all(assignments) else "WARNING","DUPLICATE_MEDIA":"WARNING" if bundle.get("assetCount",0)>bundle.get("uniqueVisualGroups",0) else "PASS","CTA_HOLD_LENGTH":"PASS" if (spec.purpose or "").upper()!="CTA" or min(1.8,duration)<=2 else "WARNING"};return {"path":output,"artifactId":output.name,"sceneIndex":spec.order_index,"durationSeconds":duration,"width":width,"height":height,"motion":{**motion.metadata(),"shots":shot_meta,"shotCount":len(shots),"productMediaSummary":{key:bundle.get(key) for key in ("ownerId","assetCount","uniqueVisualGroups","videoCount","detailCount","heroCount","diversityScore","diversityLevel","qualityCheck","warning")},"mediaDiversity":bundle.get("diversityLevel"),"mediaRepetition":repetition,"maxVisualStagnationSeconds":round(max((x.end-x.start for x in shots),default=duration),3),"patternInterruptCount":sum(x.pattern_interrupt_type!="NONE" for x in shots),"avatarHidden":bool(spec.avatar_asset_id and not any(x.persona_visible for x in shots)),"headline":headline,"headlineAdjusted":headline_adjusted,"shotsAdjusted":shots_adjusted,"ctaFocusDurationSeconds":round(min(1.8,duration),3) if (spec.purpose or "").upper()=="CTA" else None,"visualChecks":{**checks,**commercial,**media_checks,"SHOT_VISUAL_DELTA":visual_delta}}}
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
