import json,shutil, struct, subprocess, sys
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.core.config import settings
from apps.api.app.db.models import Creative, MediaAsset, MediaJob
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.operations import log_decision
from apps.api.app.services.voice_engine import VOICE_PROFILES,chatterbox_probe,chatterbox_profile,resolve_local_reference
from apps.api.app.services.brand_assets import AVATAR_STATES

MIMES={".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp",".mp4":"video/mp4",".mov":"video/quicktime",".webm":"video/webm"}
ASSET_TYPES={"PRODUCT_IMAGE","PRODUCT_VIDEO","AVATAR_IMAGE","LOGO","BACKGROUND","OVERLAY"};OWNER_TYPES={"CANDIDATE","CREATIVE","BRAND","AVATAR"}
def image_info(data:bytes,mime:str):
    if mime=="image/png" and data[:8]==b"\x89PNG\r\n\x1a\n" and len(data)>=26:
        width,height=struct.unpack(">II",data[16:24]);return width,height,data[25] in (4,6)
    if mime=="image/webp" and data[:4]==b"RIFF" and data[8:12]==b"WEBP" and len(data)>=30:
        if data[12:16]==b"VP8X":return (1+int.from_bytes(data[24:27],"little"),1+int.from_bytes(data[27:30],"little"),bool(data[20]&0x10))
    if mime=="image/jpeg" and data[:2]==b"\xff\xd8":
        i=2
        while i+9<len(data):
            if data[i]!=255:i+=1;continue
            marker=data[i+1];size=int.from_bytes(data[i+2:i+4],"big")
            if marker in range(0xC0,0xC4):return (int.from_bytes(data[i+7:i+9],"big"),int.from_bytes(data[i+5:i+7],"big"),False)
            i+=2+size
    raise ValueError("Imagem inválida ou não decodificável")
def image_dimensions(data:bytes,mime:str):return image_info(data,mime)[:2]
def add_asset(db:Session,filename:str,mime:str,data:bytes,asset_type:str,owner_type:str,owner_id:str|None,logical_name:str,character:str|None=None,avatar_state:str|None=None,classification:str|None=None):
    if asset_type not in ASSET_TYPES or owner_type not in OWNER_TYPES:raise ValueError("Tipo ou proprietário do asset inválido")
    ext=Path(filename).suffix.lower()
    if ext not in MIMES:raise ValueError("Extensão de imagem não permitida")
    if MIMES[ext]!=mime:raise ValueError("MIME não corresponde à extensão")
    if not data or len(data)>settings.media_asset_max_bytes:raise ValueError("Tamanho de imagem inválido")
    is_video=asset_type=="PRODUCT_VIDEO";width=height=None;has_alpha=False
    if not is_video:width,height,has_alpha=image_info(data,mime)
    metadata={}
    if asset_type=="AVATAR_IMAGE":
        character=(character or "").upper();avatar_state=(avatar_state or "NEUTRAL").upper()
        if owner_type!="AVATAR" or character not in AVATAR_STATES or avatar_state not in AVATAR_STATES[character]:raise ValueError("Personagem ou expressão do avatar inválidos")
        metadata={"speaker":character,"state":avatar_state,"hasAlpha":has_alpha}
    elif asset_type in {"PRODUCT_IMAGE","PRODUCT_VIDEO"}:
        from apps.api.app.services.product_media import CLASSIFICATIONS
        normalized=(classification or "").upper();metadata={"classification":normalized if normalized in CLASSIFICATIONS else ("VIDEO_CLIP" if is_video else "UNKNOWN_PRODUCT_MEDIA"),"hasAlpha":has_alpha}
    storage=MediaStorage();relative,path=storage.asset_path(ext)
    try:
        path.write_bytes(data)
        if is_video:
            probe=subprocess.run([settings.ffprobe_path,"-v","error","-show_streams","-show_format","-of","json",str(path)],shell=False,capture_output=True,text=True,timeout=30,check=True);info=json.loads(probe.stdout);video=next((x for x in info.get("streams",[]) if x.get("codec_type")=="video"),{});width,height=int(video.get("width") or 0) or None,int(video.get("height") or 0) or None;metadata.update({"duration":float(info.get("format",{}).get("duration") or 0),"fps":video.get("avg_frame_rate"),"hasAudio":any(x.get("codec_type")=="audio" for x in info.get("streams",[])),"usableStart":0,"usableEnd":float(info.get("format",{}).get("duration") or 0)})
        row=MediaAsset(asset_type=asset_type,owner_type=owner_type,owner_id=owner_id,logical_name=logical_name[:200],relative_path=relative,mime_type=mime,width=width,height=height,file_size_bytes=len(data),metadata_=metadata);db.add(row);db.flush();log_decision(db,"OPERATOR","MEDIA_ASSET","MEDIA_ASSET_ADDED",row.id,metadata={"assetType":asset_type,"ownerType":owner_type,"ownerId":owner_id,"character":character,"avatarState":avatar_state,"classification":metadata.get("classification")});db.commit();db.refresh(row);return row
    except Exception:path.unlink(missing_ok=True);db.rollback();raise
def create_job(db:Session,creative:Creative,render_type:str):
    if creative.status!="APPROVED":raise ValueError("Somente criativos aprovados podem gerar mídia")
    profiles={"PREVIEW":(540,960),"STANDARD":(1080,1920)}
    if render_type not in profiles:raise ValueError("Perfil de render inválido")
    w,h=profiles[render_type];row=MediaJob(creative_id=creative.id,render_type=render_type,status="QUEUED",width=w,height=h,fps=30,video_codec="h264",audio_codec="aac",expected_duration_seconds=creative.estimated_duration_seconds,progress_percent=0);db.add(row);db.flush();log_decision(db,"OPERATOR","MEDIA_JOB","MEDIA_JOB_CREATED",row.id,metadata={"creativeId":creative.id,"renderType":render_type});db.commit();db.refresh(row);return row
def binary_diagnostic(executable:str):
    try:
        result=subprocess.run([executable,"-version"],shell=False,capture_output=True,text=True,timeout=5,check=False)
        line=(result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else None
        return {"status":"AVAILABLE" if result.returncode==0 else "ERROR","version":line}
    except (FileNotFoundError,subprocess.TimeoutExpired,OSError) as exc:return {"status":"NOT_CONFIGURED","version":None,"message":type(exc).__name__}
def piper_probe(command:list[str],mode:str):
    """Non-destructive availability probe; never synthesizes audio."""
    attempts=[[*command,"--help"]] if mode=="MODULE" else [[*command,"--version"],[*command,"--help"]]
    for index,args in enumerate(attempts):
        result=subprocess.run(args,shell=False,capture_output=True,text=True,timeout=5,check=False)
        if result.returncode==0:
            if mode=="MODULE":return True,"Piper module available"
            if index==0:
                line=(result.stdout or result.stderr).splitlines();return True,(line[0] if line else "Piper CLI available")
            return True,"Piper CLI available"
    return False,None
def diagnostics():
    if settings.tts_provider.upper()=="CHATTERBOX":
        profiles={}
        for name in VOICE_PROFILES:
            try:resolve_local_reference(chatterbox_profile(name)["reference"]);profiles[name]={"status":"AVAILABLE","reasonCode":None}
            except ValueError:profiles[name]={"status":"INVALID","reasonCode":"REFERENCE_AUDIO_INVALID"}
        status,reason=chatterbox_probe(settings.chatterbox_python_path)
        if status=="AVAILABLE" and any(x["status"]!="AVAILABLE" for x in profiles.values()):status,reason="ERROR","TTS_CONFIGURATION_INVALID"
        tts={"status":status,"provider":"CHATTERBOX","invocationMode":"ISOLATED","reasonCode":reason,"version":"Chatterbox import available" if status=="AVAILABLE" else None,"profiles":profiles}
        try:storage={"status":"AVAILABLE" if MediaStorage().writable() else "ERROR"}
        except OSError:storage={"status":"ERROR"}
        return {"ffmpeg":binary_diagnostic(settings.ffmpeg_path),"ffprobe":binary_diagnostic(settings.ffprobe_path),"tts":tts,"storage":storage}
    models={"BRUNO":(settings.tts_model_bruno,settings.tts_model_config_bruno),"CAROL":(settings.tts_model_carol,settings.tts_model_config_carol),"NARRATOR":(settings.tts_model_narrator,settings.tts_model_config_narrator)};profiles={}
    for name,(model,configured_json) in models.items():
        config=configured_json or (str(Path(model).with_suffix(Path(model).suffix+".json")) if model else "")
        if not model:profiles[name]={"status":"NOT_CONFIGURED","reasonCode":"MODEL_NOT_CONFIGURED"}
        elif not Path(model).is_file():profiles[name]={"status":"INVALID","reasonCode":"MODEL_NOT_FOUND"}
        elif not config or not Path(config).is_file():profiles[name]={"status":"INVALID","reasonCode":"MODEL_CONFIG_NOT_FOUND"}
        else:profiles[name]={"status":"AVAILABLE","reasonCode":None}
    mode=settings.tts_invocation_mode.upper();command=([settings.tts_python_path or sys.executable,"-m",settings.tts_python_module] if mode=="MODULE" else [settings.tts_executable_path]);executable=command[0]
    if not settings.tts_provider or not executable:tts={"status":"NOT_CONFIGURED","provider":settings.tts_provider or None,"invocationMode":mode,"reasonCode":"TTS_EXECUTABLE_NOT_CONFIGURED","profiles":profiles}
    elif not Path(executable).is_file() and not shutil.which(executable):tts={"status":"ERROR","provider":settings.tts_provider,"invocationMode":mode,"reasonCode":"TTS_EXECUTABLE_NOT_FOUND","profiles":profiles}
    else:
        try:
            responds,description=piper_probe(command,mode);available=responds and all(x["status"]=="AVAILABLE" for x in profiles.values());tts={"status":"AVAILABLE" if available else "ERROR","provider":settings.tts_provider,"invocationMode":mode,"reasonCode":None if available else "TTS_CONFIGURATION_INVALID","version":description,"profiles":profiles}
        except (OSError,subprocess.TimeoutExpired):tts={"status":"ERROR","provider":settings.tts_provider,"invocationMode":mode,"reasonCode":"TTS_EXECUTABLE_NOT_FOUND","profiles":profiles}
    try:storage={"status":"AVAILABLE" if MediaStorage().writable() else "ERROR"}
    except OSError:storage={"status":"ERROR"}
    return {"ffmpeg":binary_diagnostic(settings.ffmpeg_path),"ffprobe":binary_diagnostic(settings.ffprobe_path),"tts":tts,"storage":storage}
