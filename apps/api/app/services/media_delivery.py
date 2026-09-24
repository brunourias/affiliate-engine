from __future__ import annotations
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import hashlib,hmac,ipaddress,json,mimetypes,secrets,shutil
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from sqlalchemy.orm import Session
from apps.api.app.core.config import settings
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.operations import log_decision

ALLOWED={"image/png","image/jpeg","video/mp4"};PROFILE="media-delivery-v1"
def now():return datetime.now(timezone.utc)
def digest(path:Path)->str:
    value=sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):value.update(chunk)
    return value.hexdigest()

class PublicMediaReachabilityValidator:
    def validate(self,base_url:str|None,allow_http_local=False)->str:
        if not base_url:return "UNCONFIGURED"
        try:
            parts=urlsplit(base_url);host=parts.hostname
            if not host:return "UNKNOWN"
            local=host.lower()=="localhost"
            try:local=local or ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
            except ValueError:pass
            if local:return "LOCAL_ONLY"
            if parts.scheme!="https":return "HTTPS_REQUIRED"
            return "VALID"
        except ValueError:return "UNKNOWN"

class MediaDeliveryStrategyResolver:
    def resolve(self,channel:str,connector:str,format:str,media_type:str,file_size:int,provider_available:bool,resumable_supported=False)->str:
        if channel=="INSTAGRAM" and format=="VIDEO_SHORT" and resumable_supported:return "RESUMABLE_UPLOAD"
        if channel=="INSTAGRAM" and media_type in {"image/png","image/jpeg"}:return "TEMPORARY_PUBLIC_URL"
        if channel=="INSTAGRAM" and media_type=="video/mp4":return "TEMPORARY_PUBLIC_URL"
        return "LOCAL_ONLY"

class SignedTemporaryMediaProvider:
    def __init__(self,db:Session|None=None,base_url:str|None=None,secret:str|None=None,ttl_minutes:int|None=None,development=False):self.db=db;self.base_url=(base_url if base_url is not None else settings.public_media_base_url).rstrip("/");self.secret=secret if secret is not None else settings.public_media_signing_secret;self.ttl=ttl_minutes or settings.public_media_ttl_minutes;self.development=development
    def status(self)->dict:
        reach=PublicMediaReachabilityValidator().validate(self.base_url)
        ready=bool(self.secret) and reach=="VALID"
        return {"provider":"SIGNED_TEMPORARY_MEDIA","status":"AVAILABLE" if ready else "DEVELOPMENT_ONLY" if self.development and self.base_url else "NOT_CONFIGURED","externalReadiness":"READY" if ready else "NOT_READY_FOR_EXTERNAL_DELIVERY","reachability":reach,"publicBaseConfigured":bool(self.base_url)}
    def stage(self,relative:str,channel="INSTAGRAM",ttl_minutes:int|None=None)->dict:
        source=MediaStorage().resolve(relative)
        if not source.is_file():raise ValueError("MEDIA_SOURCE_EXISTS")
        mime=mimetypes.guess_type(source.name)[0]
        if mime not in ALLOWED:raise ValueError("MEDIA_TYPE_ALLOWED")
        checksum=digest(source);created=now();expires=created+timedelta(minutes=ttl_minutes or self.ttl);asset_id=str(uuid4());root=MediaStorage().resolve(f"public_delivery/{asset_id}");root.mkdir(parents=True);target=root/("asset"+source.suffix.lower());shutil.copy2(source,target)
        signing_secret=self.secret or ("development-only-"+secrets.token_urlsafe(32) if self.development else "");token=self._token(asset_id,int(expires.timestamp()),signing_secret) if signing_secret else None;public_url=f"{self.base_url}/api/v1/public-media/{asset_id}?token={token}" if self.base_url and token else None;provider=self.status();record={"id":asset_id,"sourcePath":relative,"stagedPath":f"public_delivery/{asset_id}/{target.name}","publicUrl":public_url,"contentType":mime,"fileSize":target.stat().st_size,"checksum":checksum,"createdAt":created.isoformat(),"expiresAt":expires.isoformat(),"status":"AVAILABLE" if public_url else "STAGED","accessTokenId":sha256(token.encode()).hexdigest()[:16] if token else None,"provider":"SIGNED_TEMPORARY_MEDIA","sourceFingerprint":checksum,"channel":channel,"profileVersion":PROFILE,"reachability":provider["reachability"]}
        (root/"asset.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
        if self.db:log_decision(self.db,"SYSTEM","HOSTED_MEDIA_ASSET","MEDIA_ASSET_STAGED",asset_id,metadata={"sourceFingerprint":checksum,"expiresAt":record["expiresAt"],"provider":record["provider"],"accessTokenId":record["accessTokenId"]});self.db.commit()
        return record
    @staticmethod
    def _token(asset_id:str,expires:int,secret:str)->str:
        nonce=secrets.token_urlsafe(18);payload=f"{asset_id}.{expires}.{nonce}";signature=hmac.new(secret.encode(),payload.encode(),hashlib.sha256).hexdigest();return f"{expires}.{nonce}.{signature}"
    @staticmethod
    def verify(asset_id:str,token:str,secret:str,at:datetime|None=None)->bool:
        try:expires_text,nonce,signature=token.split(".",2);expires=int(expires_text);payload=f"{asset_id}.{expires}.{nonce}";expected=hmac.new(secret.encode(),payload.encode(),hashlib.sha256).hexdigest();return hmac.compare_digest(signature,expected) and int((at or now()).timestamp())<=expires
        except (ValueError,AttributeError):return False

class MediaDeliveryEngine:
    def __init__(self,db:Session,provider:SignedTemporaryMediaProvider|None=None):self.db=db;self.provider=provider or SignedTemporaryMediaProvider(db)
    def plan(self,candidate_id:str,channel:str,format:str,assets:list[str],write_log=False)->dict:
        provider=self.provider.status();items=[]
        for index,relative in enumerate(assets):
            path=MediaStorage().resolve(relative);mime=mimetypes.guess_type(path.name)[0] or "application/octet-stream";strategy=MediaDeliveryStrategyResolver().resolve(channel,"INSTAGRAM_CONTENT_PUBLISHING",format,mime,path.stat().st_size if path.is_file() else 0,provider["status"]=="AVAILABLE");items.append({"order":index,"sourcePath":relative,"contentType":mime,"strategy":strategy,"sourceExists":path.is_file()})
        requirements=[]
        if provider["reachability"]=="UNCONFIGURED":requirements.append("PUBLIC_MEDIA_BASE_NOT_CONFIGURED")
        if provider["reachability"] in {"LOCAL_ONLY","HTTPS_REQUIRED","UNKNOWN"}:requirements.append("PUBLIC_MEDIA_SOURCE_REQUIRED")
        if not self.provider.secret:requirements.append("PUBLIC_MEDIA_SIGNING_SECRET_NOT_CONFIGURED")
        payload={"candidate":candidate_id,"channel":channel,"format":format,"assets":[{"path":x["sourcePath"],"checksum":digest(MediaStorage().resolve(x["sourcePath"])) if x["sourceExists"] else None} for x in items],"strategy":"TEMPORARY_PUBLIC_URL","provider":"SIGNED_TEMPORARY_MEDIA","ttl":self.provider.ttl,"profile":PROFILE};fp=sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest();result={"publicationCandidateId":candidate_id,"channel":channel,"format":format,"assets":items,"strategy":"TEMPORARY_PUBLIC_URL","provider":provider,"requirements":requirements,"readiness":"READY" if not requirements else "NOT_READY","warnings":[],"fingerprint":fp,"profileVersion":PROFILE,"remoteRequestExecuted":False}
        if write_log:log_decision(self.db,"SYSTEM","MEDIA_DELIVERY","MEDIA_DELIVERY_PLANNED",candidate_id,metadata={"channel":channel,"format":format,"requirements":requirements,"readiness":result["readiness"],"fingerprint":fp});self.db.commit()
        return result
    def prepare(self,candidate_id:str,channel:str,format:str,assets:list[str])->dict:
        plan=self.plan(candidate_id,channel,format,assets,write_log=True);hosted=[self.provider.stage(x["sourcePath"],channel) for x in plan["assets"]];external=all(x["status"]=="AVAILABLE" and x["reachability"]=="VALID" for x in hosted);result={**plan,"hostedAssets":hosted,"readiness":"READY" if external else "NOT_READY","requirements":[] if external else list(dict.fromkeys(plan["requirements"]+["PUBLIC_MEDIA_SOURCE_REQUIRED"]))};root=MediaStorage().resolve(f"public_delivery/manifests/{candidate_id}");root.mkdir(parents=True,exist_ok=True);(root/"media-delivery-manifest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");return result
    def revoke(self,asset_id:str)->dict:
        record,path=load_asset(asset_id);record["status"]="REVOKED";path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8");log_decision(self.db,"OPERATOR","HOSTED_MEDIA_ASSET","MEDIA_ASSET_REVOKED",asset_id,metadata={"accessTokenId":record.get("accessTokenId")});self.db.commit();return record

class MediaDeliveryCleaner:
    def __init__(self,db:Session):self.db=db
    def clean(self,at:datetime|None=None)->dict:
        at=at or now();removed=[];root=MediaStorage().resolve("public_delivery")
        for manifest in root.glob("*/asset.json") if root.exists() else []:
            record=json.loads(manifest.read_text(encoding="utf-8"));expired=datetime.fromisoformat(record["expiresAt"])<at
            if expired or record["status"] in {"REVOKED","EXPIRED"}:shutil.rmtree(manifest.parent);removed.append(record["id"])
        log_decision(self.db,"SYSTEM","MEDIA_DELIVERY","MEDIA_DELIVERY_CLEANED",metadata={"removedCount":len(removed),"assetIds":removed});self.db.commit();return {"removed":removed}

def load_asset(asset_id:str)->tuple[dict,Path]:
    if not asset_id or any(x in asset_id for x in ("/","\\","..")):raise FileNotFoundError
    path=MediaStorage().resolve(f"public_delivery/{asset_id}/asset.json")
    if not path.is_file():raise FileNotFoundError
    return json.loads(path.read_text(encoding="utf-8")),path

def resumable_upload_plan(source_file:str)->dict:
    path=MediaStorage().resolve(source_file)
    if not path.is_file():raise ValueError("MEDIA_SOURCE_EXISTS")
    return {"sourceFile":source_file,"contentType":mimetypes.guess_type(path.name)[0],"fileSize":path.stat().st_size,"checksum":digest(path),"targetPlatform":"INSTAGRAM","status":"PLANNED","remoteRequestExecuted":False}
