from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
import json,os,shutil
from pathlib import Path
from uuid import NAMESPACE_URL,uuid5
from sqlalchemy.orm import Session
from apps.api.app.db.models import Creative
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.operations import log_decision

def fingerprint(value:dict)->str:return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

class EnvironmentCredentialProvider:
    NAMES={"TIKTOK":["TIKTOK_CLIENT_KEY","TIKTOK_CLIENT_SECRET"],"YOUTUBE":["YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET"],"META":["META_APP_ID","META_APP_SECRET"]}
    def configured(self,channel:str)->bool:return all(bool(os.getenv(name)) for name in self.NAMES.get(channel,[]))
    def describe(self,channel:str)->dict:return {"configured":self.configured(channel),"requiredEnvironmentVariables":self.NAMES.get(channel,[])}

class PublicationConnector:
    def capabilities(self)->dict:raise NotImplementedError
    def validate_connection(self)->dict:return {"status":"NOT_CONFIGURED"}
    def validate_package(self,package:dict)->dict:return {"valid":bool(package.get("assetFiles")),"readinessStatus":package.get("readinessStatus")}
    def prepare(self,package:dict)->dict:raise NotImplementedError
    def publish(self,package:dict):raise PermissionError("Publicação via API está desabilitada nesta versão.")
    def fetch_status(self,execution_id:str)->dict:return {"executionId":execution_id,"status":"PLANNED","remoteRequestExecuted":False}
    def begin_authorization(self):raise NotImplementedError
    def handle_callback(self):raise NotImplementedError
    def refresh_token(self):raise NotImplementedError
    def disconnect(self):raise NotImplementedError

class TikTokPublicationConnector(PublicationConnector):
    def __init__(self,mode:str):self.mode=mode
    def capabilities(self)->dict:return {"connector":"TIKTOK_CONTENT_POSTING","connectorDomain":"CONTENT_PUBLISHING","channel":"TIKTOK","supportedModes":["EXPORT_ONLY","ASSISTED_UPLOAD","DIRECT_PUBLISH"],"supportedFormats":["VIDEO_SHORT","STATIC_CARD","CAROUSEL"],"supportsDraftUpload":True,"supportsDirectPublish":True,"supportsStatusPolling":True,"supportsWebhooks":True,"requiresOAuth":self.mode!="EXPORT_ONLY","requiredScopes":[] if self.mode=="EXPORT_ONLY" else ["video.upload"] if self.mode=="ASSISTED_UPLOAD" else ["video.publish"],"requiresAppReview":self.mode=="DIRECT_PUBLISH","requiresAudit":self.mode=="DIRECT_PUBLISH","supportsPhotos":True,"supportsVideo":True,"supportsCarousel":True,"source":"TIKTOK_CONTENT_POSTING_API_DOCUMENTATION","lastReviewedAt":"2026-09-24","adsManagementSupported":False}
    def validate_connection(self)->dict:return {"status":"READY" if self.mode=="EXPORT_ONLY" else "NOT_CONFIGURED","accountDisplayName":None,"accountId":None,"scopes":[],"expiresAt":None,"lastValidatedAt":None}

class YouTubePublicationConnector(PublicationConnector):
    def __init__(self,mode:str):self.mode=mode
    def capabilities(self)->dict:return {"connector":"YOUTUBE_DATA_API","connectorDomain":"CONTENT_PUBLISHING","channel":"YOUTUBE","supportedModes":["EXPORT_ONLY","DIRECT_PUBLISH"],"supportedFormats":["VIDEO_SHORT"],"supportsDraftUpload":False,"supportsDirectPublish":True,"supportsStatusPolling":True,"supportsWebhooks":False,"requiresOAuth":self.mode!="EXPORT_ONLY","requiredScopes":[],"requiresAppReview":False,"requiresAudit":False,"supportsPhotos":False,"supportsVideo":True,"supportsCarousel":False,"source":"YOUTUBE_DATA_API_VIDEOS_INSERT","lastReviewedAt":"2026-09-24"}
    def validate_connection(self)->dict:return {"status":"READY" if self.mode=="EXPORT_ONLY" else "NOT_CONFIGURED"}

class MetaPublicationConnector(PublicationConnector):
    def __init__(self,channel:str,mode:str):self.channel=channel;self.mode=mode
    def capabilities(self)->dict:return {"connector":"META_STUB","connectorDomain":"CONTENT_PUBLISHING","channel":self.channel,"supportedModes":["EXPORT_ONLY"],"supportedFormats":[],"supportsDraftUpload":"UNKNOWN","supportsDirectPublish":"UNKNOWN","supportsStatusPolling":"UNKNOWN","supportsWebhooks":"UNKNOWN","requiresOAuth":self.mode!="EXPORT_ONLY","requiredScopes":[],"requiresAppReview":"UNKNOWN","requiresAudit":"UNKNOWN","supportsPhotos":"UNKNOWN","supportsVideo":"UNKNOWN","supportsCarousel":"UNKNOWN","source":None,"lastReviewedAt":None}
    def validate_connection(self)->dict:return {"status":"READY" if self.mode=="EXPORT_ONLY" else "NOT_CONFIGURED"}

INSTAGRAM_AUTHORIZATION_PROFILES={
    "INSTAGRAM_LOGIN":{"id":"INSTAGRAM_LOGIN_CONTENT_PUBLISH_V1","requiredScopes":["instagram_business_basic","instagram_business_content_publish"],"source":"INSTAGRAM_API_WITH_INSTAGRAM_LOGIN","version":"2026-09-24"},
    "FACEBOOK_LOGIN":{"requiredScopes":["instagram_basic","instagram_content_publish","pages_show_list","pages_read_engagement"],"source":"INSTAGRAM_API_WITH_FACEBOOK_LOGIN","version":"2026-09-24"},
}
class InstagramPublicationConnector(PublicationConnector):
    MAX_CAROUSEL_ITEMS=10
    def __init__(self,mode:str,authorization_profile="INSTAGRAM_LOGIN",connection:dict|None=None):self.mode=mode;self.authorization_profile=authorization_profile;self.connection=connection
    def capabilities(self)->dict:
        profile=INSTAGRAM_AUTHORIZATION_PROFILES[self.authorization_profile]
        return {"connector":"INSTAGRAM_CONTENT_PUBLISHING","connectorDomain":"CONTENT_PUBLISHING","channel":"INSTAGRAM","supportedModes":["EXPORT_ONLY","DIRECT_PUBLISH"],"supportedFormats":["STATIC_CARD","CAROUSEL","VIDEO_SHORT"],"supportsDraftUpload":False,"supportsDirectPublish":True,"supportsStatusPolling":True,"supportsWebhooks":False,"requiresOAuth":self.mode!="EXPORT_ONLY","requiredScopes":[] if self.mode=="EXPORT_ONLY" else profile["requiredScopes"],"authorizationProfile":self.authorization_profile,"authorizationProfileId":profile.get("id",self.authorization_profile),"authorizationSource":profile["source"],"requiresAppReview":True,"requiresAudit":False,"supportsPhotos":True,"supportsVideo":True,"supportsCarousel":True,"supportsReels":True,"publishingLimitCheckSupported":True,"maxCarouselItems":self.MAX_CAROUSEL_ITEMS,"source":"INSTAGRAM_CONTENT_PUBLISHING_API_DOCUMENTATION","lastReviewedAt":"2026-09-24","adsManagementSupported":False,"connectionRequirements":{"professionalAccountRequired":True,"supportedAccountTypes":["BUSINESS","CREATOR"],"oauthRequired":True,"accountIdRequired":True,"mediaHostingRequired":True}}
    def validate_connection(self)->dict:
        if self.mode=="EXPORT_ONLY":return {"status":"READY","reasonCodes":[],"accountType":None,"igAccountId":None,"scopes":[]}
        value=self.connection or {"status":"NOT_CONFIGURED","accountType":None,"accountId":None,"scopes":[]};reasons=[]
        if value.get("status")!="CONNECTED":reasons.append("INSTAGRAM_CONNECTION_REQUIRED")
        if value.get("accountType") not in {"BUSINESS","CREATOR"}:reasons.append("PROFESSIONAL_ACCOUNT_REQUIRED")
        if "instagram_business_content_publish" not in value.get("scopes",[]):reasons.append("INSTAGRAM_PERMISSION_REQUIRED")
        return {**value,"status":"READY" if not reasons else value.get("status","NOT_CONFIGURED"),"reasonCodes":reasons,"igAccountId":value.get("accountId")}
    def validate_package(self,package:dict,media_delivery="LOCAL_ONLY",account_type:str|None=None,connected=False)->dict:
        if self.connection:
            connected=connected or self.connection.get("status")=="CONNECTED";account_type=account_type or self.connection.get("accountType")
        delivery_ready=isinstance(media_delivery,dict) and media_delivery.get("readiness")=="READY" and media_delivery.get("provider",{}).get("reachability")=="VALID";delivery_name=media_delivery.get("strategy") if isinstance(media_delivery,dict) else media_delivery;reasons=[];assets=package.get("assetFiles",[]);format=package.get("format")
        if format=="CAROUSEL" and len(assets)>self.MAX_CAROUSEL_ITEMS:reasons.append("INSTAGRAM_CONTAINER_LIMIT_EXCEEDED")
        if self.mode=="DIRECT_PUBLISH":
            if not connected:reasons.append("INSTAGRAM_CONNECTION_REQUIRED")
            if account_type not in {"BUSINESS","CREATOR"}:reasons.append("PROFESSIONAL_ACCOUNT_REQUIRED")
            if self.connection and "instagram_business_content_publish" not in self.connection.get("scopes",[]):reasons.append("INSTAGRAM_PERMISSION_REQUIRED")
            if delivery_name not in {"PUBLIC_URL","TEMPORARY_PUBLIC_URL"} or not (delivery_ready or media_delivery=="PUBLIC_URL"):reasons.append("PUBLIC_MEDIA_SOURCE_REQUIRED")
            if package.get("manualReviewRequired"):reasons.append("DISCLOSURE_REQUIREMENT_UNKNOWN")
        return {"valid":not reasons,"readiness":"READY" if not reasons else "NOT_READY","reasonCodes":list(dict.fromkeys(reasons)),"mediaDeliveryStrategy":delivery_name}
    def execution_plan(self,package:dict,media_delivery="LOCAL_ONLY",account_type:str|None=None,connected=False)->dict:
        validation=self.validate_package(package,media_delivery,account_type,connected);assets=package.get("assetFiles",[]);format=package.get("format")
        if "INSTAGRAM_CONTAINER_LIMIT_EXCEEDED" in validation["reasonCodes"]:raise ValueError("Instagram carousel supports at most 10 items")
        steps=[{"code":"VALIDATE_PACKAGE"},{"code":"VALIDATE_CONNECTION"},{"code":"VALIDATE_ACCOUNT_TYPE"},{"code":"CHECK_PUBLISHING_LIMIT"},{"code":"PREPARE_PUBLIC_MEDIA"}]
        if format=="CAROUSEL":steps.extend({"code":"CREATE_ITEM_CONTAINER","assetIndex":i,"asset":asset} for i,asset in enumerate(assets));steps.extend([{"code":"WAIT_FOR_CONTAINER","reasonCode":"INSTAGRAM_CONTAINER_PROCESSING_REQUIRED"},{"code":"CREATE_CAROUSEL_CONTAINER","childrenCount":len(assets)},{"code":"PUBLISH_CONTAINER"},{"code":"FETCH_RESULT"}])
        elif format=="VIDEO_SHORT":steps.extend([{"code":"CREATE_MEDIA_CONTAINER","mediaType":"REELS","asset":assets[0] if assets else None},{"code":"WAIT_FOR_CONTAINER","reasonCode":"INSTAGRAM_CONTAINER_PROCESSING_REQUIRED"},{"code":"PUBLISH_CONTAINER"},{"code":"FETCH_RESULT"}])
        else:steps.extend([{"code":"CREATE_MEDIA_CONTAINER","mediaType":"IMAGE","asset":assets[0] if assets else None},{"code":"PUBLISH_CONTAINER"},{"code":"FETCH_RESULT"}])
        payload={"package":package["packageFingerprint"],"connector":"INSTAGRAM_CONTENT_PUBLISHING","mode":self.mode,"mediaDelivery":media_delivery,"accountType":account_type};execution_fingerprint=fingerprint(payload)
        return {"executionId":str(uuid5(NAMESPACE_URL,execution_fingerprint)),"candidateId":package["publicationCandidateId"],"packageFingerprint":package["packageFingerprint"],"connector":"INSTAGRAM_CONTENT_PUBLISHING","connectorDomain":"CONTENT_PUBLISHING","mode":self.mode,"channel":"INSTAGRAM","format":format,"status":"WAITING_FOR_MEDIA_HOSTING" if "PUBLIC_MEDIA_SOURCE_REQUIRED" in validation["reasonCodes"] else "PLANNED","readiness":validation["readiness"],"requirements":validation["reasonCodes"],"mediaDeliveryStrategy":media_delivery,"steps":steps,"igAccountId":None,"creationId":None,"containerIds":[],"platformMediaId":None,"executionFingerprint":execution_fingerprint,"remoteRequestExecuted":False}

class LocalExportPublicationConnector(PublicationConnector):
    def __init__(self,db:Session):self.db=db
    def capabilities(self)->dict:return {"connector":"LOCAL_EXPORT","connectorDomain":"CONTENT_PUBLISHING","channel":"ANY","supportedModes":["EXPORT_ONLY"],"supportedFormats":["STATIC_CARD","CAROUSEL","VIDEO_SHORT"],"supportsDraftUpload":False,"supportsDirectPublish":False,"supportsStatusPolling":False,"supportsWebhooks":False,"requiresOAuth":False,"requiredScopes":[],"requiresAppReview":False,"requiresAudit":False,"supportsPhotos":True,"supportsVideo":True,"supportsCarousel":True,"source":"LOCAL_EXPORT","lastReviewedAt":"2026-09-24"}
    def validate_connection(self)->dict:return {"status":"READY"}
    def prepare(self,package:dict)->dict:
        creative=self.db.get(Creative,package["creativeId"]);caption=CaptionComposer().compose(creative.cta or "",package.get("disclosurePlan") or {},[],[]);execution_fingerprint=fingerprint({"package":package["packageFingerprint"],"connector":"LOCAL_EXPORT","account":None,"mode":"EXPORT_ONLY"});execution_id=str(uuid5(NAMESPACE_URL,execution_fingerprint));root=MediaStorage().resolve(f"publication_exports/{package['creativeId']}/{execution_id}");assets_dir=root/"assets"
        if root.exists():return json.loads((root/"manifest.json").read_text(encoding="utf-8"))
        assets_dir.mkdir(parents=True);exported=[]
        for index,relative in enumerate(package["assetFiles"],1):
            source=MediaStorage().resolve(relative)
            if not source.is_file():raise ValueError(f"Asset de publicação não encontrado: {index}")
            target=assets_dir/f"{index:02}_{source.name}";shutil.copy2(source,target);exported.append(f"assets/{target.name}")
        disclosure=(package.get("disclosurePlan") or {}).get("displayText") or "";destination=package.get("destinationUrl") or "";checklist=self._checklist(package,exported)
        root.joinpath("caption.txt").write_text(caption["text"],encoding="utf-8");root.joinpath("destination.txt").write_text(destination,encoding="utf-8");root.joinpath("disclosure.txt").write_text(disclosure,encoding="utf-8");root.joinpath("checklist.txt").write_text("\n".join(f"- {x}" for x in checklist),encoding="utf-8")
        if any((package.get("trackingPlan") or {}).values()):root.joinpath("tracking.txt").write_text(json.dumps(package["trackingPlan"],ensure_ascii=False,indent=2),encoding="utf-8")
        manifest={"executionId":execution_id,"publicationCandidateId":package["publicationCandidateId"],"creativeId":package["creativeId"],"experimentId":package["experimentId"],"channel":package["channel"],"distributionMode":package["distributionMode"],"placement":package["placement"],"format":package["format"],"connector":"LOCAL_EXPORT","connectorMode":"EXPORT_ONLY","connectorDomain":"CONTENT_PUBLISHING","assets":exported,"caption":caption,"cta":creative.cta,"destinationUrl":destination,"affiliateUrl":package.get("affiliateUrl"),"disclosurePlan":package.get("disclosurePlan"),"audioPlan":package.get("audioPlan"),"trackingPlan":package.get("trackingPlan"),"publicationProfile":"local-export-v1","packageFingerprint":package["packageFingerprint"],"executionFingerprint":execution_fingerprint,"exportFingerprint":fingerprint({"package":package["packageFingerprint"],"assets":exported,"caption":caption}),"readinessStatus":package["readinessStatus"],"blockers":package.get("blockers",[]),"warnings":package.get("warnings",[]),"status":"EXPORTED","createdAt":datetime.now(timezone.utc).isoformat(),"remoteRequestExecuted":False,"checklist":checklist}
        root.joinpath("manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8");log_decision(self.db,"OPERATOR","PUBLICATION_EXPORT","PUBLICATION_EXPORT_CREATED",execution_id,metadata={"creativeId":package["creativeId"],"connector":"LOCAL_EXPORT","mode":"EXPORT_ONLY","status":"EXPORTED","fingerprint":manifest["exportFingerprint"]});self.db.commit();return manifest
    @staticmethod
    def _checklist(package:dict,assets:list[str])->list[str]:
        result=[f"Plataforma: {package['channel']}",f"Formato: {package['format']}",f"Usar {len(assets)} arquivos preparados."]
        if package.get("audioPlan",{}).get("status")=="AUDIO_PLATFORM_SELECTION_REQUIRED":result.append("AUDIO_PLATFORM_SELECTION_REQUIRED — selecionar música comercial na plataforma.")
        if package.get("manualReviewRequired"):result.append("DISCLOSURE — revisão manual obrigatória antes da publicação.")
        result.extend(["Conferir a URL de destino.","Conferir o CTA.","Não marcar como publicado até confirmação humana."]);return result

class CaptionComposer:
    def compose(self,base:str,disclosure:dict,hashtags:list[str],mentions:list[str])->dict:
        parts=[base.strip()] if base.strip() else [];text=disclosure.get("displayText") or disclosure.get("text")
        if text and text not in parts:parts.append(text.strip())
        parts.extend(x for x in hashtags if x);parts.extend(x for x in mentions if x);value="\n\n".join(parts)
        return {"text":value,"hashtags":hashtags,"mentions":mentions,"disclosureText":text,"maxLength":None,"validationStatus":"VALID"}

class PublicationConnectorRegistry:
    def __init__(self,db:Session):self.db=db
    def resolve(self,channel:str,mode:str)->PublicationConnector|None:
        if mode=="EXPORT_ONLY":return LocalExportPublicationConnector(self.db)
        if channel=="TIKTOK" and mode in {"ASSISTED_UPLOAD","DIRECT_PUBLISH"}:return TikTokPublicationConnector(mode)
        if channel=="INSTAGRAM" and mode=="DIRECT_PUBLISH":
            from apps.api.app.services.instagram_oauth import InstagramConnectionService
            return InstagramPublicationConnector(mode,connection=InstagramConnectionService(self.db).public())
        if channel=="FACEBOOK":return MetaPublicationConnector(channel,mode)
        if channel in {"YOUTUBE","YOUTUBE_SHORTS"} and mode=="DIRECT_PUBLISH":return YouTubePublicationConnector(mode)
        return None
    def options(self,channel:str)->list[dict]:
        result=[]
        for mode in ("EXPORT_ONLY","ASSISTED_UPLOAD","DIRECT_PUBLISH"):
            connector=self.resolve(channel,mode);connection=connector.validate_connection() if connector else {"status":"NOT_CONFIGURED"};result.append({"channel":channel,"mode":mode,"readiness":connection["status"] if connector else "NOT_SUPPORTED","connection":connection,"capabilities":connector.capabilities() if connector else None,"actionEnabled":mode=="EXPORT_ONLY"})
        return result

class PublicationExecutionPlanner:
    STEPS={"EXPORT_ONLY":["validate package","copy approved assets","write caption and disclosure","write manual checklist"],"ASSISTED_UPLOAD":["validate connection","query capabilities","initialize upload","transfer media","wait for platform acceptance","user completes post manually"],"DIRECT_PUBLISH":["validate connection and scopes","query creator info","initialize post","transfer media","confirm explicit operator approval","fetch status"]}
    def create(self,package:dict,connector:str,mode:str,account_id:str|None=None)->dict:
        execution_fingerprint=fingerprint({"package":package["packageFingerprint"],"connector":connector,"account":account_id,"mode":mode});return {"executionId":str(uuid5(NAMESPACE_URL,execution_fingerprint)),"candidateId":package["publicationCandidateId"],"packageFingerprint":package["packageFingerprint"],"connector":connector,"mode":mode,"channel":package["channel"],"accountId":account_id,"status":"PLANNED","steps":self.STEPS[mode],"executionFingerprint":execution_fingerprint,"remoteRequestExecuted":False}
