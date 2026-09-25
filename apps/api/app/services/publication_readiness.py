from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session

from apps.api.app.db.models import MediaAsset
from apps.api.app.services.channel_adaptation import ChannelAssetAdaptationEngine
from apps.api.app.services.format_decision import CreativeDistributionPlan
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.operations import log_decision


TIKTOK_AUDIO_PROFILE={"required":True,"minDurationSeconds":2,"maxDurationSeconds":None,"acceptedFormats":["MP3"],"source":"TIKTOK_ADS_DOCUMENTATION","lastReviewedAt":"2026-09-24"}


class AudioRequirementResolver:
    def resolve(self,channel:str,distribution_mode:str,placement:str,format:str)->dict:
        if channel=="INSTAGRAM" and format=="STATIC_CARD":return {"status":"KNOWN","required":False,"minDurationSeconds":None,"maxDurationSeconds":None,"acceptedFormats":[],"source":"INSTAGRAM_STATIC_IMAGE_PROFILE","lastReviewedAt":"2026-09-25"}
        if (channel,distribution_mode,placement,format)==("TIKTOK","PAID_AD","TIKTOK_IN_FEED","CAROUSEL"):
            return {"status":"KNOWN",**TIKTOK_AUDIO_PROFILE}
        return {"status":"UNKNOWN","required":None,"minDurationSeconds":None,"maxDurationSeconds":None,"acceptedFormats":[],"source":None,"lastReviewedAt":None}


class AudioLicenseValidator:
    def validate(self,metadata:dict)->str:
        status=str(metadata.get("licenseStatus") or "UNKNOWN").upper()
        if status=="NOT_ALLOWED" or metadata.get("commercialUseAllowed") is False:return "NOT_ALLOWED"
        if status=="VERIFIED" and metadata.get("commercialUseAllowed") is True and metadata.get("licenseReference"):return "VERIFIED"
        return status if status in {"UNVERIFIED","UNKNOWN"} else "UNKNOWN"


class DisclosureRequirementResolver:
    def resolve(self,channel:str,distribution_mode:str,affiliate_relationship:str,creative_format:str,configured:dict|None=None)->dict:
        configured=configured or {};status=str(configured.get("requirementStatus") or "UNKNOWN").upper()
        if status not in {"REQUIRED","NOT_REQUIRED","UNKNOWN"}:status="UNKNOWN"
        return {"requirementStatus":status,"required":True if status=="REQUIRED" else False if status=="NOT_REQUIRED" else None,"displayText":configured.get("text"),"placement":configured.get("placement"),"allowedPlacements":["CAPTION","CREATIVE","PLATFORM_LABEL","MULTIPLE"],"platformToolRequired":bool(configured.get("platformToolRequired")),"platformTool":configured.get("platformTool"),"source":"MANUAL_CONFIGURATION" if status!="UNKNOWN" else None,"lastReviewedAt":None,"affiliateRelationship":affiliate_relationship,"manualReviewRequired":status=="UNKNOWN"}


class PublicationReadinessEngine:
    PROFILE_VERSION="publication-readiness-v1"
    def __init__(self,db:Session):self.db=db
    @staticmethod
    def valid_url(value:str|None)->bool:
        if not value:return False
        try:parts=urlsplit(value);return parts.scheme in {"http","https"} and bool(parts.netloc)
        except ValueError:return False
    @staticmethod
    def tracking_plan(url:str|None,tracking:dict|None)->dict:
        tracking=tracking or {};mapped={"utmSource":"utm_source","utmMedium":"utm_medium","utmCampaign":"utm_campaign","utmContent":"utm_content"};effective=url
        if url and tracking:
            parts=urlsplit(url);query=dict(parse_qsl(parts.query,keep_blank_values=True))
            for key,param in mapped.items():
                if tracking.get(key) and param not in query:query[param]=str(tracking[key])
            effective=urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),parts.fragment))
        return {**{key:tracking.get(key) for key in mapped},"effectiveDestinationUrl":effective}
    def evaluate(self,creative_id:str,audio_plan:dict|None=None,disclosure_plan:dict|None=None,tracking:dict|None=None,distribution_mode="PAID_AD",format="CAROUSEL",write_log=False,channel:str|None=None)->dict:
        plan=CreativeDistributionPlan(self.db).create(creative_id,[format],distribution_mode=distribution_mode,channel=channel);candidate=plan["publicationCandidates"][0]
        placement=CreativeDistributionPlan._placement(candidate["channel"],format);variant=ChannelAssetAdaptationEngine(self.db).current_variant(creative_id,candidate["channel"],distribution_mode,placement,format)
        audio_requirement=AudioRequirementResolver().resolve(candidate["channel"],distribution_mode,placement,format);audio=self._audio(audio_requirement,audio_plan)
        disclosure=DisclosureRequirementResolver().resolve(candidate["channel"],distribution_mode,"AFFILIATE_LINK",format,disclosure_plan);disclosure.update(self._disclosure_status(disclosure,disclosure_plan))
        blockers=[];warnings=[]
        def block(code,message,source):blockers.append({"code":code,"severity":"BLOCKER","status":"OPEN","message":message,"source":source})
        if candidate["approvalStatus"]!="APPROVED":block("APPROVAL_REQUIRED","O Creative precisa estar aprovado.","CREATIVE")
        if candidate["compatibility"] in {"UNKNOWN","NOT_SUPPORTED"}:block("CHANNEL_COMPATIBILITY_UNRESOLVED","A compatibilidade com o canal não está resolvida.","CHANNEL_PROFILE")
        if not variant:block("CHANNEL_VARIANT_REQUIRED","A variante do canal precisa estar atualizada.","CHANNEL_VARIANT")
        elif variant.get("adaptationStatus")!="UP_TO_DATE":block("OUTPUT_NOT_UP_TO_DATE","A variante do canal está desatualizada.","CHANNEL_VARIANT")
        if audio["status"] in {"AUDIO_MISSING"}:block("AUDIO_REQUIRED","Adicione áudio ou registre a seleção de música na plataforma.","AUDIO_PROFILE")
        elif audio["status"]=="AUDIO_INVALID":block("AUDIO_INVALID","O áudio selecionado não atende aos requisitos.","AUDIO_PROFILE")
        elif audio["status"]=="AUDIO_PLATFORM_SELECTION_REQUIRED":warnings.append({"code":"AUDIO_PLATFORM_SELECTION_REQUIRED","message":"Selecione música comercial na plataforma antes de publicar.","source":"AUDIO_PLAN"})
        if disclosure["requirementStatus"]=="UNKNOWN":block("DISCLOSURE_REQUIREMENT_UNKNOWN","O disclosure precisa de revisão manual.","DISCLOSURE_PROFILE")
        elif disclosure["requirementStatus"]=="REQUIRED" and disclosure["status"]=="MISSING":block("DISCLOSURE_MISSING","Configure o disclosure obrigatório.","DISCLOSURE_PLAN")
        elif disclosure["status"]=="PLATFORM_TOOL_REQUIRED":warnings.append({"code":"PLATFORM_DISCLOSURE_TOOL_REQUIRED","message":"Ative a identificação exigida na plataforma.","source":"DISCLOSURE_PLAN"})
        if not self.valid_url(candidate.get("destinationUrl")):block("DESTINATION_URL_MISSING","Informe uma URL de destino válida.","DISTRIBUTION_PLAN")
        if not self.valid_url(candidate.get("affiliateUrl")):block("AFFILIATE_URL_MISSING","Informe uma URL de afiliado válida.","CAMPAIGN")
        tracking_plan=self.tracking_plan(candidate.get("destinationUrl"),tracking)
        fingerprint_payload={"candidate":candidate["inputFingerprint"],"variant":variant.get("variantFingerprint") if variant else None,"audio":audio_plan or {},"disclosure":disclosure_plan or {},"destination":candidate.get("destinationUrl"),"tracking":tracking_plan,"profile":self.PROFILE_VERSION}
        fingerprint=sha256(json.dumps(fingerprint_payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest();status="BLOCKED" if blockers else "READY_WITH_WARNINGS" if warnings else "READY"
        result={"publicationCandidateId":str(uuid5(NAMESPACE_URL,f"{creative_id}:{candidate['channel']}:{distribution_mode}:{placement}:{format}")),"creativeId":creative_id,"experimentId":candidate["experimentId"],"channel":candidate["channel"],"distributionMode":distribution_mode,"placement":placement,"format":format,"assetFiles":candidate["assetPaths"],"channelVariantFingerprint":variant.get("variantFingerprint") if variant else None,"audioRequirement":audio_requirement,"audioPlan":audio,"disclosurePlan":disclosure,"destinationUrl":candidate.get("destinationUrl"),"affiliateUrl":candidate.get("affiliateUrl"),"trackingPlan":tracking_plan,"approvalStatus":candidate["approvalStatus"],"requirements":candidate["requirements"],"warnings":warnings,"blockers":blockers,"readinessStatus":status,"manualReviewRequired":disclosure["manualReviewRequired"],"packageFingerprint":fingerprint,"publicationEnabled":False}
        if write_log:log_decision(self.db,"SYSTEM","PUBLICATION_CANDIDATE","PUBLICATION_READINESS_EVALUATED",result["publicationCandidateId"],metadata={"blockers":blockers,"warnings":warnings,"readiness":status,"fingerprint":fingerprint});self.db.commit()
        return result
    def prepare(self,creative_id:str,channel:str|None=None,**kwargs)->dict:
        result=self.evaluate(creative_id,write_log=True,channel=channel,**kwargs);directory=MediaStorage().resolve(f"publication_packages/{creative_id}/{result['publicationCandidateId']}");directory.mkdir(parents=True,exist_ok=True);manifest=directory/"manifest.json"
        previous=None
        if manifest.is_file():
            try:previous=json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError,json.JSONDecodeError):previous=None
        result["packageStatus"]="OUTDATED" if previous and previous.get("packageFingerprint")!=result["packageFingerprint"] else result["readinessStatus"]
        result["manualPublicationInstructions"]=self._instructions(result);manifest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        for action,key in (("AUDIO_PLAN_CREATED","audioPlan"),("DISCLOSURE_PLAN_CREATED","disclosurePlan"),("PUBLICATION_PACKAGE_PREPARED",None)):log_decision(self.db,"OPERATOR","PUBLICATION_PACKAGE",action,result["publicationCandidateId"],metadata=result if key is None else result[key])
        self.db.commit();return result
    def _audio(self,requirement:dict,plan:dict|None)->dict:
        plan=plan or {};mode=str(plan.get("mode") or "NONE").upper()
        if requirement["status"]=="KNOWN" and requirement.get("required") is False:return {**plan,"mode":mode,"status":"AUDIO_NOT_REQUIRED","licenseStatus":"NOT_APPLICABLE"}
        if requirement["status"]=="UNKNOWN":return {**plan,"mode":mode,"status":"AUDIO_MISSING","licenseStatus":"UNKNOWN"}
        if mode=="PLATFORM" and plan.get("sourceType")=="TIKTOK_CML" and plan.get("selectionRequiredAtPublication") is True:return {**plan,"mode":mode,"status":"AUDIO_PLATFORM_SELECTION_REQUIRED","licenseStatus":"VERIFIED"}
        if mode!="LOCAL" or not plan.get("mediaAssetId"):return {**plan,"mode":mode,"status":"AUDIO_MISSING","licenseStatus":"UNKNOWN"}
        asset=self.db.get(MediaAsset,plan["mediaAssetId"]);metadata=(asset.metadata_ or {}) if asset else {};license_status=AudioLicenseValidator().validate(metadata);audio_format=str(metadata.get("format") or (Path(asset.relative_path).suffix[1:] if asset else "")).upper();duration=metadata.get("duration") or metadata.get("durationSeconds")
        valid=bool(asset and asset.active and audio_format in requirement["acceptedFormats"] and duration is not None and float(duration)>=requirement["minDurationSeconds"] and license_status=="VERIFIED")
        return {**plan,"mode":mode,"status":"AUDIO_PRESENT" if valid else "AUDIO_INVALID","durationSeconds":duration,"format":audio_format or None,"licenseStatus":license_status,"sourceType":metadata.get("sourceType","LOCAL_FILE")}
    @staticmethod
    def _disclosure_status(requirement:dict,plan:dict|None)->dict:
        plan=plan or {};status=str(plan.get("status") or "MISSING").upper()
        if requirement["requirementStatus"]=="NOT_REQUIRED":status="NOT_APPLICABLE"
        elif requirement["platformToolRequired"] and status!="PRESENT":status="PLATFORM_TOOL_REQUIRED"
        elif status=="PRESENT" and not (plan.get("text") or plan.get("platformTool")):status="MISSING"
        return {"status":status}
    @staticmethod
    def _instructions(result:dict)->list[str]:
        instructions=[f"Use {len(result['assetFiles'])} arquivos preparados para {result['placement']}."]
        if result["audioPlan"]["status"]=="AUDIO_PLATFORM_SELECTION_REQUIRED":instructions.append("Selecione música comercial na plataforma antes de publicar.")
        if result["disclosurePlan"]["status"]=="PRESENT":instructions.append(f"Aplique o disclosure configurado em {result['disclosurePlan'].get('placement') or 'placement definido pelo operador'}.")
        instructions.extend(["Use a URL de destino validada.","Confirme o preview e publique manualmente."]);return instructions
