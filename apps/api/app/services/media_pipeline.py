from dataclasses import dataclass,replace
from datetime import datetime,timezone
from math import ceil
from typing import Protocol
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.core.config import settings
from apps.api.app.db.models import Campaign,Creative,CreativeScene,MediaAsset,MediaJob
from apps.api.app.services.operations import log_decision
from apps.api.app.services.brand_assets import normalize_avatar_state
from apps.api.app.services.voice_director import pace_target_status,timing_polish
from apps.api.app.services.commercial_polish import dead_air_metrics

ACTIVE={"PREPARING","RENDERING_AUDIO","RENDERING_SCENES","COMPOSING","VALIDATING"};TERMINAL={"COMPLETED","FAILED","CANCELED"}
@dataclass(frozen=True)
class SceneRenderSpec:
    scene_id:str;order_index:int;scene_type:str;speaker:str;narration_text:str|None;on_screen_text:str|None;visual_instruction:str|None;avatar_state:str|None;requested_duration_seconds:float;resolved_duration_seconds:float;product_asset_ids:list[str];avatar_asset_id:str|None;disclosure_text:str|None;required_warning_codes:list[str];layout_type:str;avatar_resolution:str="NOT_APPLICABLE";transition_in:str="FADE";transition_out:str="FADE";timeline_start_seconds:float=0.0;timeline_end_seconds:float=0.0;subtitle_start_seconds:float=0.0;subtitle_end_seconds:float=0.0;purpose:str|None=None
class VoiceRenderer(Protocol):
    def render(self,spec:SceneRenderSpec)->dict:...
class SceneRenderer(Protocol):
    def render(self,spec:SceneRenderSpec,audio:dict|None,width:int,height:int)->dict:...
class TimelineComposer(Protocol):
    def compose(self,scenes:list[dict],width:int,height:int,fps:int)->dict:...
class MediaValidator(Protocol):
    def validate(self,output:dict)->dict:...
class PipelineError(RuntimeError):
    def __init__(self,code,message,details=None):super().__init__(message);self.code=code;self.details=details or {}
class FakeVoiceRenderer:
    def __init__(self,fail=False):self.fail=fail
    def render(self,spec):
        if self.fail:raise PipelineError("VOICE_RENDER_FAILED","Não foi possível simular a voz.")
        words=len((spec.narration_text or "").split());return {"audioId":f"audio-{spec.scene_id}","durationSeconds":max(.4,words/2.6)}
class FakeSceneRenderer:
    def __init__(self,fail_scene=None):self.fail_scene=fail_scene
    def render(self,spec,audio,width,height):
        if spec.order_index==self.fail_scene:raise PipelineError("SCENE_RENDER_FAILED",f"Não foi possível montar a cena {spec.order_index+1}.")
        return {"artifactId":f"scene-{spec.scene_id}","sceneIndex":spec.order_index,"durationSeconds":spec.resolved_duration_seconds,"width":width,"height":height}
class FakeTimelineComposer:
    def __init__(self,fail=False):self.fail=fail
    def compose(self,scenes,width,height,fps):
        if self.fail:raise PipelineError("COMPOSE_FAILED","Não foi possível compor a timeline.")
        return {"outputId":"fake-timeline","durationSeconds":sum(x["durationSeconds"] for x in scenes),"width":width,"height":height,"fps":fps}
class FakeMediaValidator:
    def __init__(self,status="VALID"):self.status=status
    def validate(self,output):return {"status":self.status,"details":{"logicalPipeline":True,**output}}
class AssetResolver:
    def __init__(self,db:Session):self.db=db
    def product_ids(self,creative:Creative):
        campaign=self.db.get(Campaign,creative.campaign_id)
        if not campaign:return []
        return list(self.db.scalars(select(MediaAsset.id).where(MediaAsset.asset_type.in_(("PRODUCT_IMAGE","PRODUCT_VIDEO")),MediaAsset.owner_type=="CANDIDATE",MediaAsset.owner_id==campaign.candidate_id,MediaAsset.active==True)))
    def avatar(self,speaker,state):
        normalized=normalize_avatar_state(speaker,state)
        if not normalized:return None,"NOT_APPLICABLE"
        rows=self.db.scalars(select(MediaAsset).where(MediaAsset.asset_type=="AVATAR_IMAGE",MediaAsset.owner_type=="AVATAR",MediaAsset.active==True)).all()
        for target in dict.fromkeys((normalized,"NEUTRAL")):
            for row in rows:
                meta=row.metadata_ or {}
                if str(meta.get("speaker","")).upper()==speaker.upper() and str(meta.get("state","NEUTRAL")).upper()==target:return row.id,("EXACT" if target==normalized else "NEUTRAL")
        return None,"BRAND_FALLBACK"
    def avatar_id(self,speaker,state):return self.avatar(speaker,state)[0]
def layout(scene_type,has_product,has_avatar):
    if scene_type=="AVATAR":return "AVATAR" if has_avatar else "BRAND_FALLBACK"
    if scene_type=="PRODUCT" and has_product:return "PRODUCT"
    if scene_type in {"WARNING","CTA"}:return scene_type if has_product or has_avatar else "BRAND_FALLBACK"
    if scene_type=="MIXED":return "MIXED" if has_product or has_avatar else "BRAND_FALLBACK"
    if scene_type=="TEXT":return "TEXT"
    if scene_type in {"COMPARISON","PROS_CONS","PRICE","BROLL"}:return "MIXED" if has_product or has_avatar else "BRAND_FALLBACK"
    return "BRAND_FALLBACK"
def build_specs(db,creative,scenes):
    resolver=AssetResolver(db);products=resolver.product_ids(creative);result=[]
    for render_index,scene in enumerate(scenes):
        normalized_state=normalize_avatar_state(scene.speaker,scene.avatar_state);avatar,resolution=resolver.avatar(scene.speaker,normalized_state);requested=float(scene.duration_seconds or 3);narration=timing_polish(scene.narration_text,scene.purpose);result.append(SceneRenderSpec(scene.id,render_index,scene.scene_type,scene.speaker,narration,scene.on_screen_text,scene.visual_instruction,normalized_state,requested,requested,products,avatar,creative.disclosure_text if scene.scene_type=="CTA" else None,scene.required_warning_codes or [],layout(scene.scene_type,bool(products),bool(avatar)),resolution,purpose=scene.purpose))
    return result
def stage(db,job,status,progress,index=None):
    db.refresh(job)
    if job.status=="CANCELED":raise PipelineError("JOB_CANCELED","Renderização cancelada pelo operador.")
    job.status=status;job.current_stage=status;job.progress_percent=max(job.progress_percent,progress)
    if index is not None:job.current_scene_index=index
    log_decision(db,"SYSTEM","MEDIA_JOB",f"MEDIA_{status}",job.id,metadata={"progress":job.progress_percent,"sceneIndex":index});db.commit()
def run_pipeline(db:Session,job_id:str,voice=None,scene_renderer=None,composer=None,validator=None):
    job=db.get(MediaJob,job_id)
    if not job or job.status!="PREPARING":return
    try:
        creative=db.get(Creative,job.creative_id)
        if not all((voice,scene_renderer,composer,validator)):
            if settings.media_pipeline_mode=="LOCAL":
                from apps.api.app.services.local_media import local_adapters
                voice,scene_renderer,composer,validator=local_adapters(db,job,creative)
            else:voice=voice or FakeVoiceRenderer();scene_renderer=scene_renderer or FakeSceneRenderer();composer=composer or FakeTimelineComposer();validator=validator or FakeMediaValidator()
        scenes=db.scalars(select(CreativeScene).where(CreativeScene.creative_id==creative.id).order_by(CreativeScene.order_index)).all();specs=build_specs(db,creative,scenes);job.total_scenes=len(specs);db.commit();stage(db,job,"RENDERING_AUDIO",10)
        resolved=[];batch_audio=voice.render_batch(specs) if hasattr(voice,"render_batch") else None;timeline_cursor=0.0
        for i,spec in enumerate(specs):
            audio=batch_audio[i] if batch_audio is not None else (voice.render(spec) if spec.narration_text else None);duration=float(audio["durationSeconds"]) if audio else spec.requested_duration_seconds;end=timeline_cursor+duration;resolved_spec=replace(spec,resolved_duration_seconds=duration,timeline_start_seconds=timeline_cursor,timeline_end_seconds=end,subtitle_start_seconds=timeline_cursor,subtitle_end_seconds=end);resolved.append((resolved_spec,audio));timeline_cursor=end;job.progress_percent=max(job.progress_percent,10+ceil(20*(i+1)/max(1,len(specs))));job.current_scene_index=i;db.commit()
        if getattr(voice,"last_metrics",None):log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_VOICE_BATCH_RENDERED",job.id,metadata=voice.last_metrics);db.commit()
        for event in getattr(voice,"synthesis_events",[]):log_decision(db,"SYSTEM","MEDIA_JOB","VOICE_SYNTHESIS_VALIDATED" if event["validationStatus"]=="VALID" else "VOICE_SYNTHESIS_REJECTED",job.id,metadata=event)
        if getattr(voice,"synthesis_events",None):db.commit()
        log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_AUDIO_RENDERED",job.id,metadata={"sceneCount":len(specs)});stage(db,job,"RENDERING_SCENES",30)
        rendered=[]
        for i,(spec,audio) in enumerate(resolved):
            rendered_scene=scene_renderer.render(spec,audio,job.width,job.height);rendered.append(rendered_scene);job.progress_percent=max(job.progress_percent,30+ceil(45*(i+1)/max(1,len(specs))));job.current_scene_index=i;log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_SCENE_RENDERED",job.id,metadata={"sceneIndex":i,"sceneId":spec.scene_id,"requestedSpeaker":spec.speaker,"requestedAvatarState":spec.avatar_state,"resolvedAssetId":spec.avatar_asset_id,"fallback":spec.avatar_resolution,"layout":spec.layout_type,"audioDurationSeconds":float(audio["durationSeconds"]) if audio else None,"timelineStartSeconds":spec.timeline_start_seconds,"timelineEndSeconds":spec.timeline_end_seconds,"subtitleStartSeconds":spec.subtitle_start_seconds,"subtitleEndSeconds":spec.subtitle_end_seconds,**((audio or {}).get("voiceMetadata") or {}),**(rendered_scene.get("motion") or {})});db.commit()
            motion=rendered_scene.get("motion") or {}
            if i==0:log_decision(db,"SYSTEM","PRODUCT_MEDIA_BUNDLE","PRODUCT_MEDIA_ANALYZED",job.id,metadata=motion.get("productMediaSummary") or {})
            for shot in motion.get("shots",[]):
                log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_SHOT_DIRECTED",job.id,metadata={"sceneId":spec.scene_id,**shot})
                log_decision(db,"SYSTEM","MEDIA_JOB","BROLL_DIRECTED",job.id,metadata={"sceneId":spec.scene_id,"shotIndex":shot.get("shotIndex"),"assetId":shot.get("sourceAssetId"),"mediaType":shot.get("sourceMediaType"),"classification":shot.get("sourceClassification"),"duplicateGroup":shot.get("duplicateGroup"),"reason":spec.purpose or "GENERAL"})
            db.commit()
        audio_items=[audio for _,audio in resolved];dead_air=dead_air_metrics(audio_items);motions=[x.get("motion") or {} for x in rendered];duration_before=sum(float((x or {}).get("voiceMetadata",{}).get("rawDurationSeconds") or (x or {}).get("durationSeconds") or 0) for x in audio_items);duration_after=sum(x[0].resolved_duration_seconds for x in resolved);warnings=sorted({key for motion in motions for key,value in (motion.get("visualChecks") or {}).items() if value!="PASS"})
        log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_COMMERCIAL_POLISHED",job.id,metadata={"durationBefore":round(duration_before,3),"durationAfter":round(duration_after,3),"maxGapBefore":None,"maxGapAfter":dead_air["maxGapMilliseconds"],"shotsAdjusted":sum(x.get("shotsAdjusted",0) for x in motions),"headlinesAdjusted":sum(bool(x.get("headlineAdjusted")) for x in motions),"ctaAdjusted":any(x.get("ctaFocusDurationSeconds") for x in motions),"avatarsHidden":sum(bool(x.get("avatarHidden")) for x in motions),"warnings":warnings,**dead_air});db.commit()
        precise_duration=sum(x[0].resolved_duration_seconds for x in resolved);pace_status=pace_target_status(precise_duration);job.expected_duration_seconds=ceil(precise_duration);stage(db,job,"COMPOSING",80);output=composer.compose(rendered,job.width,job.height,job.fps);output["durationSeconds"]=precise_duration;log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_COMPOSING",job.id,metadata={"audioTimelineDuration":precise_duration,"targetDurationSeconds":20,"paceTargetStatus":pace_status});db.commit();stage(db,job,"VALIDATING",95);validation=validator.validate(output);validation.setdefault("details",{}).update({"targetDurationSeconds":20,"actualAudioDurationSeconds":precise_duration,"paceTargetStatus":pace_status});job.validation_status=validation["status"];job.validation_details=validation.get("details");log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_VALIDATION_COMPLETED",job.id,metadata={"status":job.validation_status,**(job.validation_details or {})});
        if job.validation_status=="INVALID":raise PipelineError("MEDIA_VALIDATION_FAILED","A validação lógica da mídia falhou.")
        final_path=composer.finalize(output) if hasattr(composer,"finalize") else None
        if final_path:
            from apps.api.app.services.media_storage import MediaStorage
            relative=final_path.resolve().relative_to(MediaStorage().root).as_posix()
            if job.render_type=="PREVIEW":job.preview_relative_path=relative
            else:job.output_relative_path=relative
            job.output_size_bytes=final_path.stat().st_size
        validated_duration=(job.validation_details or {}).get("durationSeconds")
        job.status="COMPLETED";job.current_stage="COMPLETED";job.progress_percent=100;job.actual_duration_seconds=ceil(float(validated_duration if validated_duration is not None else output["durationSeconds"]));job.completed_at=datetime.now(timezone.utc);log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_JOB_COMPLETED",job.id,metadata={"fake":not bool(final_path)});db.commit()
    except PipelineError as exc:
        db.rollback();job=db.get(MediaJob,job_id)
        if exc.code=="VOICE_SYNTHESIS_OUTLIER":
            for event in exc.details.get("attempts",[]):log_decision(db,"SYSTEM","MEDIA_JOB","VOICE_SYNTHESIS_REJECTED",job.id,metadata=event)
        if exc.code=="JOB_CANCELED":job.status="CANCELED"
        else:job.status="FAILED";job.error_code=exc.code;job.error_message=str(exc)
        job.current_stage=job.status;job.completed_at=datetime.now(timezone.utc);log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_JOB_CANCELED" if job.status=="CANCELED" else "MEDIA_JOB_FAILED",job.id,metadata={"errorCode":exc.code,**exc.details});db.commit()
    except Exception:
        db.rollback();job=db.get(MediaJob,job_id);job.status="FAILED";job.current_stage="FAILED";job.error_code="PIPELINE_NOT_AVAILABLE";job.error_message="Falha inesperada no pipeline de mídia.";job.completed_at=datetime.now(timezone.utc);log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_JOB_FAILED",job.id,metadata={"errorCode":job.error_code});db.commit()
def recover_interrupted(db:Session):
    rows=db.scalars(select(MediaJob).where(MediaJob.status.in_(ACTIVE))).all()
    for job in rows:job.status="FAILED";job.current_stage="FAILED";job.error_code="JOB_INTERRUPTED";job.error_message="A execução foi interrompida antes da conclusão.";job.completed_at=datetime.now(timezone.utc);log_decision(db,"SYSTEM","MEDIA_JOB","MEDIA_JOB_FAILED",job.id,metadata={"errorCode":"JOB_INTERRUPTED"})
    db.commit();return len(rows)
