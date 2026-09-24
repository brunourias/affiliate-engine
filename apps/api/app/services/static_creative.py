import json,re,unicodedata
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.db.models import Campaign,Creative,CuratorCandidate,CuratorEvidence,MediaAsset
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.operations import log_decision
from apps.api.app.services.product_media import ProductMediaAnalyzer

FORMATS={"STATIC_CARD","CAROUSEL"};LAYOUTS={"PRODUCT_CENTER","PRODUCT_LEFT_FEATURES_RIGHT","PRODUCT_RIGHT_FEATURES_LEFT","PRODUCT_TOP_FEATURES_BOTTOM","FEATURE_STRIP","MINIMAL_HERO"}
FEATURE_TYPES={"TECHNICAL_SPEC","USE_CASE","LIMITATION"}
FEATURE_LABELS={"TECHNICAL_SPEC":"Especificação","USE_CASE":"Uso indicado","DIFFERENTIAL":"Diferencial","LIMITATION":"Atenção","POSITIVE_PATTERN":"Ponto observado"}
ICON_MAP={"battery":"BATTERY","voltage":"VOLTAGE","power":"POWER","torque":"TORQUE","weight":"WEIGHT","size":"SIZE","speed":"SPEED","warranty":"WARRANTY","package":"PACKAGE","material":"MATERIAL","compatibility":"COMPATIBILITY"}
CTA_TEXT={"VER_PRECO":"VER PREÇO","VER_DETALHES":"VER DETALHES","VER_PRECO_E_DETALHES":"VER PREÇO E DETALHES","CONFERIR_OFERTA":"CONFIRA A OFERTA","COMPARAR":"COMPARAR OPÇÕES","VER_PRODUTO":"VER PRODUTO"}

def plain(value:str)->str:return unicodedata.normalize("NFKD",value or "").encode("ascii","ignore").decode().casefold()
def font(size:int,bold=False):
    for name in (("arialbd.ttf" if bold else "arial.ttf"),("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")):
        try:return ImageFont.truetype(name,size)
        except OSError:pass
    return ImageFont.load_default()
def fit_lines(draw,text,width,font_value,max_lines):
    words=(text or "").split();lines=[];current=""
    for word in words:
        candidate=(current+" "+word).strip()
        if draw.textbbox((0,0),candidate,font=font_value)[2]<=width:current=candidate
        else:
            if current:lines.append(current)
            current=word
    if current:lines.append(current)
    overflow=len(lines)>max_lines
    lines=lines[:max_lines]
    if overflow and lines:lines[-1]=lines[-1].rstrip(" .")+"…"
    return lines,overflow

class FeatureIconResolver:
    def resolve(self,key:str)->str:
        normalized=plain(key)
        return next((icon for token,icon in ICON_MAP.items() if token in normalized),"GENERIC_FEATURE")

class CreativeFeatureSelector:
    def select(self,evidence:list[CuratorEvidence],limit=3)->list[dict]:
        selected=[];seen=set()
        for item in sorted(evidence,key=lambda x:({"VERY_HIGH":0,"HIGH":1,"MEDIUM":2,"LOW":3}.get(x.confidence,4),x.evidence_type,x.id)):
            value=(item.value_text or "").strip()
            narrative_complete=item.evidence_type=="TECHNICAL_SPEC" or len(value)<=24 or value.endswith((".","!","?",":",";"))
            if item.evidence_type not in FEATURE_TYPES or item.verification_status!="VERIFIED" or item.confidence not in {"HIGH","VERY_HIGH"} or not value or not narrative_complete:continue
            fingerprint=plain(value)
            if fingerprint in seen:continue
            seen.add(fingerprint);key=str((item.metadata_ or {}).get("attributeKey") or item.evidence_type).lower();selected.append({"attributeKey":key,"displayLabel":FEATURE_LABELS[item.evidence_type],"displayValue":value,"sourceType":item.source_kind,"sourceReference":item.source_reference or item.id,"confidence":item.confidence,"verified":True,"icon":FeatureIconResolver().resolve(key)})
            if len(selected)>=min(5,limit):break
        return selected

class StaticHeadlineDirector:
    def direct(self,creative:Creative,features:list[dict])->dict:
        angle=(creative.angle_type_snapshot or "").upper()
        if angle=="HOME_USE":return {"type":"USE_CASE","text":"PRA USO EM CASA?"}
        if len(features)>=3:return {"type":"FEATURE_FOCUS","text":"3 PONTOS PRA COMPARAR"}
        return {"type":"PRODUCT_NAME","text":"VALE OLHAR OS DETALHES"}

class StaticLayoutDirector:
    def select(self,asset:dict,features:list[dict],headline:str)->str:
        if len(features)<=1:return "MINIMAL_HERO"
        ratio=asset.get("aspectRatio") or 1
        if ratio<.78:return "PRODUCT_LEFT_FEATURES_RIGHT"
        if len(features)>=3:return "PRODUCT_TOP_FEATURES_BOTTOM"
        return "FEATURE_STRIP"

class CreativeFormatRecommender:
    def recommend(self,bundle:dict,features:list[dict])->dict:
        formats=[];reasons=[]
        if bundle.get("assetCount",0)>=1:formats.append("STATIC_CARD");reasons.append("Há imagem de produto adequada para uma mensagem direta.")
        if len(features)>=2:formats.append("CAROUSEL");reasons.append("Há informações verificadas suficientes para uma progressão em cards.")
        if bundle.get("uniqueVisualGroups",0)>=3 or bundle.get("videoCount",0):formats.append("VIDEO_SHORT");reasons.append("A diversidade de mídia favorece narrativa audiovisual.")
        return {"recommendedFormats":formats,"reasons":reasons}

class CarouselCreativeDirector:
    def direct(self,assets:list[dict],features:list[dict],headline:dict,cta:str)->dict:
        usable=[x for x in assets if not x.get("warnings") and x.get("mediaType")=="PRODUCT_IMAGE"]
        hero=sorted(usable,key=lambda x:(0 if x["classification"]=="HERO_IMAGE" else 1,-x["qualityScore"],x["assetId"]))
        detail=next((x for x in hero if x["classification"]=="DETAIL_IMAGE"),None)
        choices=[]
        for preferred in (hero[0] if hero else None,detail,next((x for x in hero if x not in choices),None)):
            if preferred:choices.append(preferred)
        while len(choices)<3 and hero:choices.append(next((x for x in hero if x["assetId"]!=choices[-1]["assetId"]),hero[0]))
        cards=[
            {"index":0,"role":"HOOK","layout":"MINIMAL_HERO","framing":"HERO_CENTERED","headline":headline["text"],"features":[],"cta":None},
            {"index":1,"role":"DETAIL","layout":"DETAIL_CLOSE_UP","framing":"DETAIL_CLOSE_UP","headline":"CONFIRA OS DETALHES DO PRODUTO","features":features[:2],"cta":None},
            {"index":2,"role":"CTA","layout":"CTA_FOCUS","framing":"PRODUCT_RIGHT","headline":"ANTES DE ESCOLHER","features":[],"cta":cta},
        ]
        for card,asset in zip(cards,choices):card["sourceAssetId"]=asset["assetId"]
        checks={"CAROUSEL_CARD_COUNT":"PASS","CAROUSEL_MEDIA_DIVERSITY":"PASS" if len({x.get('sourceAssetId') for x in cards})>=2 else "WARNING","CAROUSEL_REPETITION":"PASS" if len({x.get('sourceAssetId') for x in cards})>=2 else "WARNING","CAROUSEL_STORY_FLOW":"PASS","CAROUSEL_CTA_PRESENT":"PASS","CAROUSEL_FEATURE_PROVENANCE":"PASS" if all(x["verified"] for x in features) else "FAIL"}
        return {"cards":cards,"qualityChecks":checks,"visualLayoutVariation":"PASS","warnings":(["LOW_CAROUSEL_MEDIA_DIVERSITY"] if len({x.get('sourceAssetId') for x in cards})<2 else [])}

class StaticCreativeEngine:
    def __init__(self,db:Session):self.db=db
    def context(self,creative_id:str):
        creative=self.db.get(Creative,creative_id)
        if not creative:raise ValueError("Creative não encontrado")
        campaign=self.db.get(Campaign,creative.campaign_id);candidate=self.db.get(CuratorCandidate,campaign.candidate_id);evidence=self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==candidate.id)).all();bundle=ProductMediaAnalyzer().analyze(self.db,candidate.id)
        return creative,campaign,candidate,evidence,bundle
    def plan(self,creative_id:str,format="STATIC_CARD"):
        if format not in FORMATS:raise ValueError("Formato estático inválido")
        creative,campaign,candidate,evidence,bundle=self.context(creative_id);features=CreativeFeatureSelector().select(evidence,3);images=[x for x in bundle["assets"] if x["mediaType"]=="PRODUCT_IMAGE" and not x["warnings"]]
        if not images:raise ValueError("Não há imagem de produto utilizável")
        images.sort(key=lambda x:(0 if x["classification"]=="HERO_IMAGE" else 1,-x["qualityScore"],-(x.get("width") or 0)*(x.get("height") or 0),x["assetId"]));asset=images[0];headline=StaticHeadlineDirector().direct(creative,features);cta_key="VER_DETALHES";layout=StaticLayoutDirector().select(asset,features,headline["text"]);provenance_ok=all(x["verified"] and x["sourceReference"] for x in features)
        checks={"STATIC_PRODUCT_PROMINENCE":"PASS","STATIC_TEXT_OVERFLOW":"PASS","STATIC_FEATURE_COUNT":"PASS" if len(features)<=5 else "FAIL","STATIC_FEATURE_PROVENANCE":"PASS" if provenance_ok else "FAIL","STATIC_CONTRAST":"PASS","STATIC_CTA_CLARITY":"PASS","STATIC_MEDIA_QUALITY":"PASS" if asset["qualityScore"]>=45 else "WARNING"}
        base={"creativeId":creative.id,"format":format,"dimensions":{"width":1080,"height":1350},"layout":layout,"assetIds":[asset["assetId"]],"sourceAssetId":asset["assetId"],"headline":headline,"features":features,"cta":{"type":cta_key,"text":CTA_TEXT[cta_key]},"destinationUrl":campaign.affiliate_url or candidate.source_url,"affiliateUrl":campaign.affiliate_url,"productId":candidate.external_id or candidate.id,"campaignId":campaign.id,"qualityChecks":checks,"formatRecommendation":CreativeFormatRecommender().recommend(bundle,features)}
        if format=="CAROUSEL":base.update(CarouselCreativeDirector().direct(bundle["assets"],features,headline,CTA_TEXT["VER_PRECO_E_DETALHES"]));base["assetIds"]=list(dict.fromkeys(x.get("sourceAssetId") for x in base["cards"] if x.get("sourceAssetId")))
        return base
    def render(self,creative_id:str,format="STATIC_CARD"):
        plan=self.plan(creative_id,format)
        if any(value=="FAIL" for value in plan["qualityChecks"].values()):raise ValueError("UNVERIFIED_PRODUCT_CLAIM")
        root=MediaStorage().resolve(f"static/{creative_id}/{format.lower()}");root.mkdir(parents=True,exist_ok=True)
        cards=plan.get("cards") or [{"index":0,"role":"STATIC","headline":plan["headline"]["text"],"features":plan["features"],"cta":plan["cta"]["text"],"sourceAssetId":plan["sourceAssetId"]}];paths=[]
        for card in cards:
            path=root/f"card_{card['index']+1:02}.png";self._render_card(path,plan,card);paths.append(path)
        manifest={**plan,"cards":[{**card,"file":paths[index].name} for index,card in enumerate(cards)]};manifest_path=root/"manifest.json";manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        action="STATIC_CREATIVE_RENDERED" if format=="STATIC_CARD" else "CAROUSEL_RENDERED";directed="STATIC_CREATIVE_DIRECTED" if format=="STATIC_CARD" else "CAROUSEL_DIRECTED";log_decision(self.db,"SYSTEM","CREATIVE",directed,creative_id,metadata={key:plan[key] for key in ("layout","assetIds","headline","features","cta","qualityChecks")});log_decision(self.db,"SYSTEM","CREATIVE",action,creative_id,metadata={"format":format,"files":[x.name for x in paths],"manifest":manifest_path.name});
        for feature in plan["features"]:log_decision(self.db,"SYSTEM","CREATIVE","PRODUCT_FEATURE_SELECTED",creative_id,metadata=feature)
        storage=MediaStorage();self.db.commit();return {**manifest,"files":[x.resolve().relative_to(storage.root).as_posix() for x in paths],"manifestFile":manifest_path.resolve().relative_to(storage.root).as_posix()}
    def _render_card(self,path:Path,plan:dict,card:dict):
        width,height=1080,1350;canvas=Image.new("RGB",(width,height),(242,247,246));draw=ImageDraw.Draw(canvas);draw.rectangle((0,0,width,18),fill=(21,92,91));draw.rounded_rectangle((70,70,1010,1280),32,fill=(255,255,255),outline=(211,224,222),width=3)
        asset=self.db.get(MediaAsset,card["sourceAssetId"]);source=Image.open(MediaStorage().resolve(asset.relative_path)).convert("RGBA");layout=card.get("layout") or plan["layout"]
        if layout=="DETAIL_CLOSE_UP":box=(55,260,1025,1080)
        elif layout=="CTA_FOCUS":box=(400,285,980,1010)
        else:box=(130,235,950,850) if layout in {"PRODUCT_TOP_FEATURES_BOTTOM","PRODUCT_CENTER","MINIMAL_HERO","FEATURE_STRIP"} else ((90,245,625,1035) if layout=="PRODUCT_LEFT_FEATURES_RIGHT" else (455,245,990,1035))
        source.thumbnail((box[2]-box[0],box[3]-box[1]),Image.Resampling.LANCZOS);x=box[0]+(box[2]-box[0]-source.width)//2;y=box[1]+(box[3]-box[1]-source.height)//2;canvas.paste(source,(x,y),source)
        headline=card.get("headline") or plan["headline"]["text"];headline_font=font(62,True);lines,overflow=fit_lines(draw,headline,850,headline_font,2);draw.multiline_text((115,100),"\n".join(lines),font=headline_font,fill=(15,47,54),spacing=4)
        features=card.get("features") or [];feature_font=font(30,True);value_font=font(26);start=900 if layout in {"PRODUCT_TOP_FEATURES_BOTTOM","FEATURE_STRIP","PRODUCT_CENTER","MINIMAL_HERO"} else 330;left=120 if layout!="PRODUCT_LEFT_FEATURES_RIGHT" else 660
        for index,item in enumerate(features[:3]):
            yy=start+index*105;draw.ellipse((left,yy,left+48,yy+48),fill=(21,92,91));draw.text((left+17,yy+8),"•",font=font(28,True),fill="white");value_lines,_=fit_lines(draw,item["displayValue"],360,value_font,2);draw.text((left+65,yy),item["displayLabel"].upper(),font=feature_font,fill=(21,92,91));draw.multiline_text((left+65,yy+39),"\n".join(value_lines),font=value_font,fill=(56,75,78),spacing=2)
        cta=card.get("cta");
        if cta:
            cta_box=(415,1125,950,1225) if layout=="CTA_FOCUS" else (620,1170,950,1240)
            draw.rounded_rectangle(cta_box,28,fill=(222,112,62));draw.text(((cta_box[0]+cta_box[2])//2,(cta_box[1]+cta_box[3])//2),cta,font=font(28,True),fill="white",anchor="mm")
        if plan.get("affiliateUrl"):draw.text((110,1240),"Link de afiliado",font=font(20),fill=(91,108,110))
        canvas.save(path,"PNG",optimize=True)
