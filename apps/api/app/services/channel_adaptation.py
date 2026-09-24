import hashlib,json,os,shutil
from pathlib import Path
from PIL import Image,ImageDraw
from sqlalchemy.orm import Session
from apps.api.app.db.models import MediaAsset
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.operations import log_decision
from apps.api.app.services.static_creative import fit_lines,font

ADAPTATION_VERSION="channel-adaptation-v1"
PROFILES={
 "TIKTOK_CAROUSEL_PAID_V1":{"profileId":"TIKTOK_CAROUSEL_PAID_V1","profileVersion":"1","channel":"TIKTOK","distributionMode":"PAID_AD","placement":"TIKTOK_IN_FEED","creativeFormat":"CAROUSEL","aspectRatio":"9:16","width":720,"height":1280,"safeAreas":{"top":80,"bottom":120,"left":40,"right":40},"fileTypes":["PNG","JPG"],"maxFileSize":None,"audioRequirement":"REQUIRED","imageCountRequirement":{"min":2,"max":35},"compatibility":"SUPPORTED_WITH_LIMITATIONS","source":"TIKTOK_ADS_DOCUMENTATION","lastReviewedAt":"2026-09-24"},
 "TIKTOK_VIDEO_PAID_V1":{"profileId":"TIKTOK_VIDEO_PAID_V1","profileVersion":"1","channel":"TIKTOK","distributionMode":"PAID_AD","placement":"TIKTOK_IN_FEED","creativeFormat":"VIDEO_SHORT","aspectRatio":"9:16","width":1080,"height":1920,"safeAreas":{"top":0,"bottom":0,"left":0,"right":0},"fileTypes":["MP4"],"maxFileSize":None,"audioRequirement":"SUPPORTED","imageCountRequirement":None,"compatibility":"SUPPORTED","source":"TIKTOK_ADS_DOCUMENTATION","lastReviewedAt":"2026-09-24"},
 "YOUTUBE_SHORTS_VIDEO_V1":{"profileId":"YOUTUBE_SHORTS_VIDEO_V1","profileVersion":"1","channel":"YOUTUBE_SHORTS","distributionMode":"ORGANIC","placement":"YOUTUBE_SHORTS","creativeFormat":"VIDEO_SHORT","aspectRatio":"9:16","width":1080,"height":1920,"safeAreas":{"top":0,"bottom":0,"left":0,"right":0},"fileTypes":["MP4"],"maxFileSize":None,"audioRequirement":"SUPPORTED","imageCountRequirement":None,"compatibility":"SUPPORTED","source":None,"lastReviewedAt":None},
}
for channel,placement in (("INSTAGRAM","INSTAGRAM_REELS"),("INSTAGRAM","INSTAGRAM_STORIES"),("FACEBOOK","FACEBOOK_REELS"),("FACEBOOK","FACEBOOK_STORIES")):
    profile_id=f"{placement}_VERTICAL_V1";PROFILES[profile_id]={"profileId":profile_id,"profileVersion":"1","channel":channel,"distributionMode":"ORGANIC","placement":placement,"creativeFormat":"VIDEO_SHORT","aspectRatio":"9:16","width":1080,"height":1920,"safeAreas":{"top":0,"bottom":0,"left":0,"right":0},"fileTypes":["MP4"],"maxFileSize":None,"audioRequirement":"SUPPORTED","imageCountRequirement":None,"compatibility":"SUPPORTED_WITH_LIMITATIONS","source":None,"lastReviewedAt":None}
for channel,placement in (("INSTAGRAM","INSTAGRAM_FEED"),("FACEBOOK","FACEBOOK_FEED")):
    for format in ("STATIC_CARD","CAROUSEL"):
        profile_id=f"{placement}_{format}_V1";PROFILES[profile_id]={"profileId":profile_id,"profileVersion":"1","channel":channel,"distributionMode":"ORGANIC","placement":placement,"creativeFormat":format,"aspectRatio":"4:5","width":1080,"height":1350,"safeAreas":{"top":40,"bottom":40,"left":40,"right":40},"fileTypes":["PNG"],"maxFileSize":None,"audioRequirement":"NOT_REQUIRED","imageCountRequirement":{"min":2,"max":None} if format=="CAROUSEL" else None,"compatibility":"SUPPORTED","source":None,"lastReviewedAt":None}

def stable_hash(value)->str:return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")).hexdigest()

class ChannelAssetProfileResolver:
    def resolve(self,channel:str,distribution_mode:str,placement:str,creative_format:str)->dict:
        match=next((x for x in PROFILES.values() if (x["channel"],x["distributionMode"],x["placement"],x["creativeFormat"])==(channel,distribution_mode,placement,creative_format)),None)
        return dict(match) if match else {"profileId":None,"profileVersion":None,"channel":channel,"distributionMode":distribution_mode,"placement":placement,"creativeFormat":creative_format,"compatibility":"UNKNOWN","aspectRatio":None,"width":None,"height":None,"safeAreas":None,"fileTypes":[],"source":None,"lastReviewedAt":None}
    def all(self)->list[dict]:return [dict(x) for x in sorted(PROFILES.values(),key=lambda x:x["profileId"])]

class AspectAdaptationPlanner:
    def plan(self,source_width:int|None,source_height:int|None,target_width:int,target_height:int,has_alpha=False)->dict:
        source_ratio=(source_width/source_height) if source_width and source_height else None;target_ratio=target_width/target_height
        strategy="CONTAIN" if source_ratio and abs(source_ratio-target_ratio)<.03 else "BACKGROUND_EXTEND"
        return {"strategy":strategy,"stretch":False,"background":"BRAND_SAFE_NEUTRAL","focalPoint":"CENTER","sourceAspectRatio":round(source_ratio,4) if source_ratio else None,"targetAspectRatio":round(target_ratio,4),"hasAlpha":has_alpha}

class SafeAreaValidator:
    def validate(self,profile:dict,elements:dict[str,tuple[int,int,int,int]])->dict:
        safe=profile["safeAreas"];bounds=(safe["left"],safe["top"],profile["width"]-safe["right"],profile["height"]-safe["bottom"]);fail=[]
        for name,box in elements.items():
            if box[0]<bounds[0] or box[1]<bounds[1] or box[2]>bounds[2] or box[3]>bounds[3]:fail.append(name)
        return {"status":"FAIL" if fail else "PASS","safeBounds":bounds,"outside":fail}

class VideoAdaptationPlanner:
    def plan(self,profile:dict)->dict:
        return {"canvas":{"width":profile["width"],"height":profile["height"],"aspectRatio":profile["aspectRatio"]},"timeline":"PRESERVE","audio":"COPY","voiceSynthesis":False,"captionText":"PRESERVE","captionTiming":"PRESERVE","captionPosition":"SAFE_AREA_REFLOW","speed":"PRESERVE"}

class ChannelAssetAdaptationEngine:
    def __init__(self,db:Session):self.db=db;self.storage=MediaStorage();self.resolver=ChannelAssetProfileResolver()
    def _source_manifest(self,creative_id:str,format:str)->tuple[Path,dict]:
        path=self.storage.resolve(f"static/{creative_id}/{format.lower()}/manifest.json")
        if not path.is_file():raise ValueError("Output de origem não encontrado")
        return path,json.loads(path.read_text(encoding="utf-8"))
    def plan(self,creative_id:str,channel:str,distribution_mode:str,placement:str,format:str,write_log=False)->dict:
        profile=self.resolver.resolve(channel,distribution_mode,placement,format)
        if profile["compatibility"]=="UNKNOWN":return {"sourceCreativeId":creative_id,"sourceFormat":format,"profile":profile,"adaptationStatus":"NOT_GENERATED","qualityChecks":{"CHANNEL_PROFILE_RESOLVED":"FAIL"},"warnings":["CHANNEL_PROFILE_UNKNOWN"]}
        source_path,source=self._source_manifest(creative_id,format);source_fingerprint=source.get("inputFingerprint") or stable_hash({key:source.get(key) for key in ("creativeId","format","dimensions","layout","assetIds","headline","features","cta","cards")})
        fingerprint=stable_hash({"sourceOutputFingerprint":source_fingerprint,"channel":channel,"distributionMode":distribution_mode,"placement":placement,"profileVersion":profile["profileVersion"],"dimensions":[profile["width"],profile["height"]],"safeAreas":profile["safeAreas"],"adaptationVersion":ADAPTATION_VERSION})
        root=self.storage.resolve(f"channel_variants/{creative_id}/{profile['profileId']}");manifest_path=root/"manifest.json";status="NOT_GENERATED"
        if manifest_path.is_file():
            try:status="UP_TO_DATE" if json.loads(manifest_path.read_text(encoding="utf-8")).get("variantFingerprint")==fingerprint else "OUTDATED"
            except (OSError,json.JSONDecodeError):status="FAILED"
        cards=[];warnings=[]
        for card in source.get("cards",[]):
            asset=self.db.get(MediaAsset,card["sourceAssetId"]);planner=AspectAdaptationPlanner().plan(asset.width,asset.height,profile["width"],profile["height"],bool((asset.metadata_ or {}).get("hasAlpha")));cards.append({"index":card["index"],"role":card["role"],"headline":card.get("headline"),"features":card.get("features") or [],"cta":card.get("cta"),"sourceAssetId":card["sourceAssetId"],"adaptationPlan":planner})
        result={"sourceCreativeId":creative_id,"sourceFormat":format,"sourceOutputFingerprint":source_fingerprint,"channel":channel,"distributionMode":distribution_mode,"placement":placement,"profileId":profile["profileId"],"profile":profile,"width":profile["width"],"height":profile["height"],"aspectRatio":profile["aspectRatio"],"cards":cards,"variantFingerprint":fingerprint,"adaptationStatus":status,"adaptationVersion":ADAPTATION_VERSION,"preservation":{"copy":True,"features":True,"provenance":True,"cardOrder":True,"cardRoles":True,"timeline":format=="VIDEO_SHORT","captionTiming":format=="VIDEO_SHORT"},"warnings":warnings}
        if write_log:log_decision(self.db,"SYSTEM","CREATIVE","CHANNEL_VARIANT_PLANNED",creative_id,metadata={"source":format,"target":placement,"profile":profile["profileId"],"safeAreas":profile["safeAreas"],"fingerprint":fingerprint});self.db.commit()
        return result
    def render(self,creative_id:str,channel:str,distribution_mode:str,placement:str,format:str)->dict:
        plan=self.plan(creative_id,channel,distribution_mode,placement,format,write_log=True)
        if plan["profile"]["compatibility"]=="UNKNOWN":raise ValueError("Perfil de canal não configurado")
        if plan["adaptationStatus"]=="UP_TO_DATE":return json.loads((self.storage.resolve(f"channel_variants/{creative_id}/{plan['profileId']}")/"manifest.json").read_text(encoding="utf-8"))
        if format not in {"STATIC_CARD","CAROUSEL"}:raise ValueError("Renderização desta variante ainda não está disponível")
        root=self.storage.resolve(f"channel_variants/{creative_id}/{plan['profileId']}");temporary=root.parent/f".{plan['profileId']}.{plan['variantFingerprint'][:12]}.tmp";shutil.rmtree(temporary,ignore_errors=True);temporary.mkdir(parents=True)
        files=[];source_assets=[];warnings=[];upscale=[];all_elements=[];text_overflow=False
        try:
            for card in plan["cards"]:
                path=temporary/f"card_{card['index']+1:02}.png";rendered=self._render_card(path,plan,card);files.append(path.name);source_assets.append(card["sourceAssetId"]);upscale.append({"cardIndex":card["index"],"sourceAssetId":card["sourceAssetId"],"upscaleFactor":rendered["upscaleFactor"]});all_elements.append(rendered["elements"]);text_overflow=text_overflow or rendered["textOverflow"]
                if rendered["upscaleFactor"]>1.5:warnings.append("SOURCE_MEDIA_LOW_RESOLUTION")
            safe_results=[SafeAreaValidator().validate(plan["profile"],x) for x in all_elements];safe_ok=all(x["status"]=="PASS" for x in safe_results);cta_ok=all("CTA" not in x["outside"] for x in safe_results)
            quality={"CHANNEL_PROFILE_RESOLVED":"PASS","CHANNEL_DIMENSIONS_VALID":"PASS","CHANNEL_ASPECT_RATIO_VALID":"PASS","CHANNEL_SAFE_AREA_VALID":"PASS" if safe_ok else "FAIL","CHANNEL_TEXT_OVERFLOW":"WARNING" if text_overflow else "PASS","CHANNEL_PRODUCT_VISIBILITY":"PASS","CHANNEL_CTA_VISIBILITY":"PASS" if cta_ok else "FAIL","CHANNEL_ASSET_QUALITY":"WARNING" if warnings else "PASS","CHANNEL_AUDIO_REQUIREMENT":"WARNING" if plan["profile"]["audioRequirement"]=="REQUIRED" else "PASS","CHANNEL_IMAGE_COUNT":"PASS" if not plan["profile"].get("imageCountRequirement") or plan["profile"]["imageCountRequirement"]["min"]<=len(files)<=(plan["profile"]["imageCountRequirement"]["max"] or len(files)) else "FAIL","CHANNEL_OUTPUT_UP_TO_DATE":"PASS"}
            warnings=list(dict.fromkeys(warnings+(["AUDIO_REQUIRED"] if plan["profile"]["audioRequirement"]=="REQUIRED" else [])))
            manifest={**plan,"files":[f"channel_variants/{creative_id}/{plan['profileId']}/{x}" for x in files],"sourceAssets":source_assets,"upscaleFactors":upscale,"qualityChecks":quality,"warnings":warnings,"safeAreaValidation":safe_results,"adaptationStatus":"UP_TO_DATE"}
            (temporary/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8");root.mkdir(parents=True,exist_ok=True)
            for item in temporary.iterdir():os.replace(item,root/item.name)
            temporary.rmdir();log_decision(self.db,"SYSTEM","CREATIVE","CHANNEL_VARIANT_RENDERED",creative_id,metadata={"source":format,"target":placement,"profile":plan["profileId"],"aspectStrategy":[x["adaptationPlan"]["strategy"] for x in plan["cards"]],"safeAreas":plan["profile"]["safeAreas"],"warnings":warnings,"fingerprint":plan["variantFingerprint"]});log_decision(self.db,"SYSTEM","CREATIVE","CHANNEL_VARIANT_VALIDATED",creative_id,metadata={"qualityChecks":quality,"warnings":warnings,"fingerprint":plan["variantFingerprint"]});self.db.commit();return manifest
        except Exception:shutil.rmtree(temporary,ignore_errors=True);raise
    def _render_card(self,path:Path,plan:dict,card:dict)->dict:
        profile=plan["profile"];width,height=profile["width"],profile["height"];safe=profile["safeAreas"];canvas=Image.new("RGB",(width,height),(242,247,246));draw=ImageDraw.Draw(canvas);draw.rectangle((0,0,width,12),fill=(21,92,91));frame=(safe["left"],max(40,safe["top"]),width-safe["right"],height-safe["bottom"]);draw.rounded_rectangle(frame,24,fill=(255,255,255),outline=(211,224,222),width=2)
        headline=card.get("headline") or "";headline_font=font(42,True);lines,overflow=fit_lines(draw,headline,width-safe["left"]-safe["right"]-70,headline_font,3);headline_box=(safe["left"]+35,safe["top"]+20,width-safe["right"]-35,safe["top"]+175);draw.multiline_text((headline_box[0],headline_box[1]),"\n".join(lines),font=headline_font,fill=(15,47,54),spacing=3)
        if card["role"]=="DETAIL":product_box=(safe["left"]+10,safe["top"]+240,width-safe["right"]-10,height-safe["bottom"]-120)
        elif card["role"]=="CTA":product_box=(width//3,safe["top"]+230,width-safe["right"]-20,height-safe["bottom"]-260)
        else:product_box=(safe["left"]+55,safe["top"]+240,width-safe["right"]-55,height-safe["bottom"]-240)
        asset=self.db.get(MediaAsset,card["sourceAssetId"]);source=Image.open(self.storage.resolve(asset.relative_path)).convert("RGBA");original=source.size;scale=min((product_box[2]-product_box[0])/max(1,source.width),(product_box[3]-product_box[1])/max(1,source.height));source=source.resize((max(1,round(source.width*scale)),max(1,round(source.height*scale))),Image.Resampling.LANCZOS);x=product_box[0]+(product_box[2]-product_box[0]-source.width)//2;y=product_box[1]+(product_box[3]-product_box[1]-source.height)//2;canvas.paste(source,(x,y),source);upscale=scale
        elements={"HEADLINE":headline_box,"PRODUCT":(x,y,x+source.width,y+source.height)}
        features=card.get("features") or []
        for index,item in enumerate(features[:3]):
            yy=height-safe["bottom"]-250+index*58;value=item["displayValue"];feature_lines,feature_overflow=fit_lines(draw,value,width-safe["left"]-safe["right"]-100,font(20),2);overflow=overflow or feature_overflow;draw.multiline_text((safe["left"]+50,yy),"\n".join(feature_lines),font=font(20),fill=(56,75,78),spacing=2)
        if cta:=card.get("cta"):
            cta_box=(safe["left"]+30,height-safe["bottom"]-115,width-safe["right"]-30,height-safe["bottom"]-35);draw.rounded_rectangle(cta_box,22,fill=(222,112,62));draw.text(((cta_box[0]+cta_box[2])//2,(cta_box[1]+cta_box[3])//2),cta,font=font(22,True),fill="white",anchor="mm");elements["CTA"]=cta_box
        canvas.save(path,"PNG",optimize=True);return {"upscaleFactor":round(upscale,3),"elements":elements,"textOverflow":overflow}
    def list(self,creative_id:str)->list[dict]:
        result=[]
        for profile in self.resolver.all():
            try:result.append(self.plan(creative_id,profile["channel"],profile["distributionMode"],profile["placement"],profile["creativeFormat"]))
            except ValueError:continue
        return result
    def current_variant(self,creative_id:str,channel:str,distribution_mode:str,placement:str,format:str)->dict|None:
        try:plan=self.plan(creative_id,channel,distribution_mode,placement,format)
        except (ValueError,KeyError,AttributeError):return None
        if plan.get("adaptationStatus")!="UP_TO_DATE":return None
        path=self.storage.resolve(f"channel_variants/{creative_id}/{plan['profileId']}/manifest.json")
        return json.loads(path.read_text(encoding="utf-8"))
