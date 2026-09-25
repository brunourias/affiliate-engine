import hashlib,json
from pathlib import Path
from uuid import NAMESPACE_URL,uuid5
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.db.models import Campaign,CampaignChannel,Creative,CreativeScene,CuratorCandidate,CuratorEvidence,MediaJob
from apps.api.app.services.media import diagnostics
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.operations import log_decision
from apps.api.app.services.product_media import ProductMediaAnalyzer
from apps.api.app.services.static_creative import CreativeFeatureSelector

FORMATS=("STATIC_CARD","CAROUSEL","VIDEO_SHORT")
PRIORITY_ORDER={"HIGH":0,"MEDIUM":1,"LOW":2,"NOT_RECOMMENDED":3}
RENDERER_VERSION={"STATIC_CARD":"static-v1g1","CAROUSEL":"carousel-v1g1","VIDEO_SHORT":"video-v1f4"}
REASON_MESSAGES={
    "STRONG_HERO_IMAGE":"Boa imagem principal disponível.","LOW_MEDIA_DIVERSITY":"Pouca diversidade de mídia disponível.",
    "HIGH_MEDIA_DIVERSITY":"Há múltiplas imagens distintas.","DETAIL_IMAGE_AVAILABLE":"Existe imagem de detalhe.",
    "VIDEO_ASSET_AVAILABLE":"Existe vídeo nativo disponível.","FEATURE_RICH_PRODUCT":"Há várias informações verificadas.",
    "LOW_VERIFIED_FEATURE_COUNT":"Há poucas informações verificadas; claims adicionais não serão criados.",
    "NARRATIVE_COMPLEXITY":"A mensagem se beneficia de desenvolvimento narrativo.","VOICE_ADDS_VALUE":"A narração pode agregar contexto.",
    "TECHNICAL_DEPENDENCY_UNAVAILABLE":"Uma dependência local necessária não está disponível.",
    "MEDIA_RESOLUTION_WARNING":"A resolução da mídia exige atenção.","SIMPLE_PRODUCT_MESSAGE":"A proposta pode ser comunicada de forma direta.",
}
UNKNOWN_RULE={"compatibility":"UNKNOWN","requirements":[],"limitations":[],"source":None,"lastReviewedAt":None}
CHANNEL_COMPATIBILITY={
    "TIKTOK":{
        "PAID_AD":{
            "STATIC_CARD":{"compatibility":"UNKNOWN","requirements":[],"limitations":[],"source":None,"lastReviewedAt":None},
            "CAROUSEL":{"compatibility":"SUPPORTED_WITH_LIMITATIONS","requirements":["MIN_IMAGE_COUNT","SHARED_DESTINATION_URL","AUDIO_REQUIRED","PLATFORM_ASPECT_RATIO_REQUIRED"],"limitations":["CHANNEL_ASSET_VARIANT_REQUIRED"],"source":"TIKTOK_ADS_DOCUMENTATION","lastReviewedAt":"2026-09-24"},
            "VIDEO_SHORT":{"compatibility":"SUPPORTED","requirements":["SHARED_DESTINATION_URL"],"limitations":[],"source":"TIKTOK_ADS_DOCUMENTATION","lastReviewedAt":"2026-09-24"},
        },
        "ORGANIC":{},"UNKNOWN":{},
    },
    "YOUTUBE_SHORTS":{"ORGANIC":{"STATIC_CARD":{"compatibility":"SUPPORTED_WITH_LIMITATIONS","requirements":[],"limitations":["PLACEMENT_CONFIGURATION_REQUIRED"],"source":None,"lastReviewedAt":None},"VIDEO_SHORT":{"compatibility":"SUPPORTED","requirements":[],"limitations":[],"source":None,"lastReviewedAt":None}},"PAID_AD":{},"UNKNOWN":{}},
    "INSTAGRAM":{"ORGANIC":{"STATIC_CARD":{"compatibility":"SUPPORTED","requirements":["SHARED_DESTINATION_URL"],"limitations":["CHANNEL_ASSET_VARIANT_REQUIRED"],"source":"INSTAGRAM_CONTENT_PUBLISHING_API_DOCUMENTATION","lastReviewedAt":"2026-09-24"}},"PAID_AD":{},"UNKNOWN":{}},
    "FACEBOOK":{"ORGANIC":{},"PAID_AD":{},"UNKNOWN":{}},
}

def canonical_hash(value:dict)->str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode("utf-8")).hexdigest()

class CreativeFormatDecisionEngine:
    def __init__(self,db:Session,diagnostics_provider=diagnostics):self.db=db;self.diagnostics_provider=diagnostics_provider
    def _context(self,creative_id:str):
        creative=self.db.get(Creative,creative_id)
        if not creative:raise ValueError("Creative não encontrado")
        campaign=self.db.get(Campaign,creative.campaign_id);candidate=self.db.get(CuratorCandidate,campaign.candidate_id)
        evidence=self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==candidate.id)).all()
        scenes=self.db.scalars(select(CreativeScene).where(CreativeScene.creative_id==creative.id).order_by(CreativeScene.order_index,CreativeScene.id)).all()
        bundle=ProductMediaAnalyzer().analyze(self.db,candidate.id)
        features=CreativeFeatureSelector().select(evidence,5)
        return creative,campaign,candidate,scenes,bundle,features
    def input_fingerprint(self,creative_id:str,format:str)->str:
        creative,campaign,_,scenes,bundle,features=self._context(creative_id)
        payload={"creativeId":creative.id,"creativeUpdatedAt":creative.updated_at,"creative":{"title":creative.title,"hook":creative.hook,"bodyScript":creative.body_script,"cta":creative.cta,"angle":creative.angle_type_snapshot,"channel":creative.target_channel},"campaignUpdatedAt":campaign.updated_at,"assets":[{"id":x["assetId"],"fingerprint":x.get("visualFingerprint"),"classification":x.get("classification"),"quality":x.get("qualityScore")} for x in bundle["assets"]],"features":features,"scenes":[{"id":x.id,"updatedAt":x.updated_at,"speaker":x.speaker,"purpose":x.purpose,"narration":x.narration_text,"screen":x.on_screen_text,"duration":x.duration_seconds} for x in scenes],"rendererVersion":RENDERER_VERSION[format],"format":format}
        return canonical_hash(payload)
    def _output_status(self,creative_id:str,format:str,fingerprint:str)->str:
        if format in {"STATIC_CARD","CAROUSEL"}:
            path=MediaStorage().resolve(f"static/{creative_id}/{format.lower()}/manifest.json")
            if not path.is_file():return "NOT_GENERATED"
            try:stored=json.loads(path.read_text(encoding="utf-8")).get("inputFingerprint")
            except (OSError,json.JSONDecodeError):return "FAILED"
            return "UP_TO_DATE" if stored==fingerprint else "OUTDATED"
        jobs=self.db.scalars(select(MediaJob).where(MediaJob.creative_id==creative_id).order_by(MediaJob.created_at.desc())).all()
        if any(x.status in {"QUEUED","PREPARING","RENDERING_AUDIO","RENDERING_SCENES","COMPOSING","VALIDATING"} for x in jobs):return "GENERATING"
        completed=next((x for x in jobs if x.status=="COMPLETED" and x.validation_status=="VALID"),None)
        if completed:return "UP_TO_DATE" if (completed.validation_details or {}).get("inputFingerprint")==fingerprint else "OUTDATED"
        return "FAILED" if any(x.status=="FAILED" for x in jobs) else "NOT_GENERATED"
    def evaluate(self,creative_id:str,technical:dict|None=None,write_log=False)->dict:
        creative,campaign,_,scenes,bundle,features=self._context(creative_id);technical=technical if technical is not None else self.diagnostics_provider()
        images=[x for x in bundle["assets"] if x["mediaType"]=="PRODUCT_IMAGE" and not x.get("warnings")];hero=any(x["classification"]=="HERO_IMAGE" for x in images);detail=any(x["classification"]=="DETAIL_IMAGE" for x in images);native_video=bundle.get("videoCount",0)>0;distinct=bundle.get("uniqueVisualGroups",0);low_resolution=any((x.get("width") or 0)<720 or (x.get("height") or 0)<720 for x in images)
        narrative=bool(creative.hook or creative.body_script or any(x.narration_text for x in scenes));complex_message=len(scenes)>=4 or len(creative.body_script or "")>300 or creative.angle_type_snapshot in {"COMPARISON","LIMITATION_FIRST","PROBLEM_SOLUTION"};requires_voice=any(x.narration_text and x.speaker!="NONE" for x in scenes)
        technical_video=all((technical.get(x) or {}).get("status")=="AVAILABLE" for x in ("storage","ffmpeg","ffprobe")) and (not requires_voice or (technical.get("tts") or {}).get("status")=="AVAILABLE")
        common=[]
        if low_resolution:common.append("MEDIA_RESOLUTION_WARNING")
        static_priority="HIGH" if hero and not complex_message else "MEDIUM" if images else "NOT_RECOMMENDED"
        static_codes=(["STRONG_HERO_IMAGE"] if hero else [])+(["SIMPLE_PRODUCT_MESSAGE"] if not complex_message else [])+(["LOW_MEDIA_DIVERSITY"] if distinct<2 else ["HIGH_MEDIA_DIVERSITY"])+common
        carousel_priority="HIGH" if distinct>=2 and detail else "MEDIUM" if distinct>=2 or len(features)>=3 else "LOW" if images else "NOT_RECOMMENDED"
        carousel_codes=(["HIGH_MEDIA_DIVERSITY"] if distinct>=2 else ["LOW_MEDIA_DIVERSITY"])+(["DETAIL_IMAGE_AVAILABLE"] if detail else [])+(["FEATURE_RICH_PRODUCT"] if len(features)>=3 else ["LOW_VERIFIED_FEATURE_COUNT"])+common
        video_priority="HIGH" if native_video or (narrative and distinct>=2 and complex_message) else "MEDIUM" if narrative else "LOW" if images else "NOT_RECOMMENDED"
        video_codes=(["VIDEO_ASSET_AVAILABLE"] if native_video else [])+(["NARRATIVE_COMPLEXITY"] if complex_message else [])+(["VOICE_ADDS_VALUE"] if requires_voice else [])+(["HIGH_MEDIA_DIVERSITY"] if distinct>=2 else ["LOW_MEDIA_DIVERSITY"])+common
        if not technical_video:video_codes.append("TECHNICAL_DEPENDENCY_UNAVAILABLE")
        specs=[("STATIC_CARD",static_priority,"READY" if images else "NOT_READY",static_codes,"LOW","LOW"),("CAROUSEL",carousel_priority,"READY" if distinct>=2 else "READY_WITH_WARNINGS" if images else "NOT_READY",carousel_codes,"LOW","MEDIUM"),("VIDEO_SHORT",video_priority,"READY" if technical_video else "NOT_READY",video_codes,"MEDIUM","HIGH")]
        recommendations=[]
        for format,priority,readiness,codes,cost,effort in specs:
            confidence="VERY_HIGH" if readiness=="READY" and priority=="HIGH" and not low_resolution else "HIGH" if readiness=="READY" else "MEDIUM" if readiness=="READY_WITH_WARNINGS" else "LOW"
            fingerprint=self.input_fingerprint(creative_id,format);warnings=[code for code in codes if code in {"LOW_MEDIA_DIVERSITY","LOW_VERIFIED_FEATURE_COUNT","TECHNICAL_DEPENDENCY_UNAVAILABLE","MEDIA_RESOLUTION_WARNING"}]
            recommendations.append({"format":format,"priority":priority,"confidence":confidence,"reasons":[{"code":code,"message":REASON_MESSAGES[code]} for code in dict.fromkeys(codes)],"warnings":warnings,"readiness":readiness,"estimatedGenerationCost":cost,"estimatedGenerationEffort":effort,"inputFingerprint":fingerprint,"outputStatus":self._output_status(creative_id,format,fingerprint)})
        result={"creativeId":creative.id,"creativeVersion":creative.updated_at.isoformat(),"recommendations":recommendations,"channelCompatibility":CHANNEL_COMPATIBILITY,"evaluatedInputs":{"assetCount":bundle["assetCount"],"uniqueVisualGroups":distinct,"detailImageAvailable":detail,"videoAssetAvailable":native_video,"verifiedFeatureCount":len(features),"narrativeAvailable":narrative}}
        if write_log:log_decision(self.db,"SYSTEM","CREATIVE","CREATIVE_FORMAT_EVALUATED",creative.id,metadata={"formats":recommendations});self.db.commit()
        return result

class CreativeDistributionPlan:
    def __init__(self,db:Session,diagnostics_provider=diagnostics):self.db=db;self.engine=CreativeFormatDecisionEngine(db,diagnostics_provider)
    def create(self,creative_id:str,selected_formats:list[str]|None=None,experiment_id:str|None=None,distribution_mode:str="UNKNOWN",write_log=False,channel:str|None=None)->dict:
        decision=self.engine.evaluate(creative_id);creative=self.db.get(Creative,creative_id);campaign=self.db.get(Campaign,creative.campaign_id)
        distribution_mode=distribution_mode.upper()
        if distribution_mode not in {"ORGANIC","PAID_AD","UNKNOWN"}:raise ValueError("Modo de distribuição inválido")
        ordered=sorted(decision["recommendations"],key=lambda x:(PRIORITY_ORDER[x["priority"]],FORMATS.index(x["format"])))
        defaults=[x["format"] for x in ordered if x["priority"] in {"HIGH","MEDIUM"} and x["readiness"]!="NOT_READY"]
        selected=defaults if selected_formats is None else list(dict.fromkeys(selected_formats))
        invalid=[x for x in selected if x not in FORMATS]
        if invalid:raise ValueError("Formato de distribuição inválido")
        experiment_id=experiment_id or creative.experiment_id or str(uuid5(NAMESPACE_URL,f"affiliate-engine:{creative.id}:format-experiment"))
        roles={};available=[x for x in ordered if x["format"] in selected]
        if available:roles["primary"]=available[0]["format"]
        if len(available)>1:roles["secondary"]=[x["format"] for x in available[1:] if x["priority"]!="LOW"]
        experimental=[x["format"] for x in available[1:] if x["priority"]=="LOW"]
        if experimental:roles["experimental"]=experimental
        channels=self.db.scalars(select(CampaignChannel).where(CampaignChannel.campaign_id==campaign.id,CampaignChannel.enabled==True)).all();enabled_channels=[self._channel_name(x.channel) for x in channels]
        requested_channel=self._channel_name(channel) if channel is not None else None
        if requested_channel is not None and requested_channel not in enabled_channels:raise ValueError("CHANNEL_NOT_ENABLED")
        configured=enabled_channels or [self._channel_name(creative.target_channel)]
        candidates=[]
        for item in ordered:
            if item["format"] not in selected:continue
            selected_channel=requested_channel or next((x for x in configured if x in CHANNEL_COMPATIBILITY),"UNKNOWN");rule=self._compatibility(selected_channel,distribution_mode,item["format"]);compatibility=rule["compatibility"]
            disclosure_text=creative.disclosure_text or campaign.disclosure_text or None;disclosure_source="CREATIVE" if creative.disclosure_text else "CAMPAIGN" if campaign.disclosure_text else "UNKNOWN";disclosure_required="UNKNOWN"
            destination=campaign.affiliate_url or None;asset_paths=self._asset_paths(creative.id,item["format"]);variant=None;placement=self._placement(selected_channel,item["format"])
            if item["format"] in {"STATIC_CARD","CAROUSEL"} and placement!="UNKNOWN":
                from apps.api.app.services.channel_adaptation import ChannelAssetAdaptationEngine
                try:variant=ChannelAssetAdaptationEngine(self.db).current_variant(creative.id,selected_channel,distribution_mode,placement,item["format"])
                except ValueError:variant=None
            if variant:asset_paths=variant["files"]
            requirements=self._requirements(rule,item["format"],asset_paths,destination,bool(variant));requirements_ok=all(x["status"]=="SATISFIED" for x in requirements)
            output_ok=bool(variant) or item["outputStatus"]=="UP_TO_DATE";approval=creative.status;creative_ready=item["readiness"]!="NOT_READY";ready=output_ok and creative_ready and approval=="APPROVED" and bool(destination) and disclosure_required!="UNKNOWN" and disclosure_source!="UNKNOWN" and compatibility in {"SUPPORTED","SUPPORTED_WITH_LIMITATIONS"} and requirements_ok
            warnings=[]
            if not output_ok:warnings.append("OUTPUT_NOT_UP_TO_DATE")
            if disclosure_required=="UNKNOWN":warnings.append("DISCLOSURE_REQUIREMENT_UNKNOWN")
            if compatibility in {"UNKNOWN","NOT_SUPPORTED"}:warnings.append("CHANNEL_COMPATIBILITY_UNRESOLVED")
            if not creative_ready:warnings.extend(item["warnings"] or ["FORMAT_NOT_READY"])
            warnings.extend(x["code"] for x in requirements if x["status"]!="SATISFIED");warnings.extend(x for x in rule["limitations"] if not (x=="CHANNEL_ASSET_VARIANT_REQUIRED" and variant))
            candidates.append({"creativeId":creative.id,"creativeVersion":decision["creativeVersion"],"format":item["format"],"channel":selected_channel,"distributionMode":distribution_mode,"compatibility":compatibility,"compatibilityMetadata":{"source":rule["source"],"lastReviewedAt":rule["lastReviewedAt"],"limitations":rule["limitations"]},"requirements":requirements,"assetPaths":asset_paths,"destinationUrl":destination,"affiliateUrl":campaign.affiliate_url,"approvalStatus":approval,"distributionReadiness":{"ready":ready,"creativeReadiness":item["readiness"],"assetExists":output_ok,"approvalStatus":approval,"destinationUrlExists":bool(destination),"affiliateUrlExists":bool(campaign.affiliate_url),"disclosureRequired":disclosure_required,"disclosurePresent":bool(disclosure_text),"disclosureText":disclosure_text,"disclosureSource":disclosure_source,"warnings":list(dict.fromkeys(warnings))},"inputFingerprint":item["inputFingerprint"],"experimentId":experiment_id,"publishedAt":None})
        result={"creativeId":creative.id,"experimentId":experiment_id,"distributionMode":distribution_mode,"recommendedSelection":defaults,"selectedFormats":selected,"roles":roles,"recommendations":decision["recommendations"],"publicationCandidates":candidates,"channelCompatibility":decision["channelCompatibility"],"metricsFoundation":{"collectionEnabled":False,"fields":["impressions","clicks","ctr","conversions","revenue","cost","format","channel","campaignId","creativeId","publishedAt"]},"fairComparison":{"fields":["creativeVersion","format","channel","publishedAt","destination","experimentId"]},"automaticGeneration":False,"publicationEnabled":False}
        if write_log:
            log_decision(self.db,"OPERATOR","CREATIVE","DISTRIBUTION_PLAN_CREATED",creative.id,metadata={"formats":selected,"experimentId":experiment_id,"fingerprints":{x["format"]:x["inputFingerprint"] for x in ordered}})
            for candidate in candidates:log_decision(self.db,"SYSTEM","CREATIVE","PUBLICATION_CANDIDATE_CREATED",creative.id,metadata=candidate)
            self.db.commit()
        return result
    def _asset_paths(self,creative_id:str,format:str)->list[str]:
        if format in {"STATIC_CARD","CAROUSEL"}:
            path=MediaStorage().resolve(f"static/{creative_id}/{format.lower()}/manifest.json")
            if path.is_file():
                try:return [f"static/{creative_id}/{format.lower()}/{x['file']}" for x in json.loads(path.read_text(encoding="utf-8")).get("cards",[]) if x.get("file")]
                except (OSError,json.JSONDecodeError):return []
        return []
    @staticmethod
    def _channel_name(value:str|None)->str:
        return {"INSTAGRAM_REELS":"INSTAGRAM","FACEBOOK_REELS":"FACEBOOK","GENERIC":"UNKNOWN"}.get(value or "",value or "UNKNOWN")
    @staticmethod
    def _compatibility(channel:str,mode:str,format:str)->dict:
        return CHANNEL_COMPATIBILITY.get(channel,{}).get(mode,{}).get(format,UNKNOWN_RULE)
    @staticmethod
    def _requirements(rule:dict,format:str,asset_paths:list[str],destination:str|None,variant_available=False)->list[dict]:
        result=[]
        for code in rule["requirements"]:
            if code=="MIN_IMAGE_COUNT":status="SATISFIED" if len(asset_paths)>=2 else "MISSING"
            elif code=="SHARED_DESTINATION_URL":status="SATISFIED" if destination else "MISSING"
            elif code=="AUDIO_REQUIRED":status="MISSING"
            elif code=="PLATFORM_ASPECT_RATIO_REQUIRED":status="SATISFIED" if variant_available or format!="CAROUSEL" else "MISSING"
            else:status="UNKNOWN"
            result.append({"code":code,"status":status})
        return result
    @staticmethod
    def _placement(channel:str,format:str)->str:
        if channel=="TIKTOK":return "TIKTOK_IN_FEED"
        if channel=="INSTAGRAM" and format=="STATIC_CARD":return "INSTAGRAM_FEED"
        if channel=="YOUTUBE_SHORTS":return "YOUTUBE_SHORTS"
        return "UNKNOWN"
