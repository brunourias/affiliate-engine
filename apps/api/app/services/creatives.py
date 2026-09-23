import re
import unicodedata
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import delete,func,select
from sqlalchemy.orm import Session
from apps.api.app.db.models import Creative,CreativeScene,Campaign,CampaignExperiment,CampaignAngle,Approval,CuratorCandidate
from apps.api.app.services.operations import log_decision

CLAIM_PATTERNS={
    "BEST_ON_MARKET_UNSUPPORTED":[r"\bmelhor(?:\s+[a-z0-9]+){0,3}\s+do mercado\b"],
    "LOWEST_PRICE_UNVERIFIED":[r"\bmenor preco\b",r"\bpreco mais baixo\b"],
    "NO_DEFECTS_CLAIM":[r"\bsem (?:nenhum(?:a)? )?(?:defeito|defeitos|falha|falhas)\b"],
    "ONE_HUNDRED_PERCENT_RECOMMENDED":[r"\b100\s*%\s*(?:recomendad[oa]|indicad[oa])\b"],
    "OWN_TEST_CLAIM":[r"\b(?:nosso teste|testamos|usamos|experimentamos|comprovamos pessoalmente)\b"],
    "PRICE_PROMOTION_CLAIM":[r"\b(?:promocao imperdivel|preco excelente|melhor preco|oferta incrivel)\b"],
    "BUY_NOW_CTA":[r"\b(?:compre agora|garanta ja|corre comprar|aproveite antes que acabe)\b"],
}
CLAIM_MESSAGES={"BEST_ON_MARKET_UNSUPPORTED":"Alegação de 'melhor do mercado' sem evidência suficiente.","LOWEST_PRICE_UNVERIFIED":"Alegação de menor preço sem verificação.","NO_DEFECTS_CLAIM":"Alegação de ausência de defeitos não permitida.","ONE_HUNDRED_PERCENT_RECOMMENDED":"Recomendação de 100% não permitida.","OWN_TEST_CLAIM":"Alegação de teste próprio não comprovada.","PRICE_PROMOTION_CLAIM":"Alegação promocional de preço não verificada.","BUY_NOW_CTA":"CTA de compra imediata não permitido."}
def normalize_text(value):
    return re.sub(r"\s+"," ","".join(c for c in unicodedata.normalize("NFKD",value or "") if not unicodedata.combining(c)).casefold()).strip()
def creative_or_404(db,id):
    row=db.get(Creative,id)
    if not row:raise HTTPException(404,"Criativo não encontrado")
    return row
def editable(row):
    if row.status in {"READY_FOR_REVIEW","APPROVED","ARCHIVED"}:raise HTTPException(409,"Criativo em revisão, aprovado ou arquivado não pode ser editado")
def create(db:Session,campaign:Campaign,data,experiment=None):
    if campaign.status!="APPROVED":raise HTTPException(409,"Somente campanhas aprovadas podem gerar criativos")
    if experiment and experiment.campaign_id!=campaign.id:raise HTTPException(409,"Experimento não pertence à campanha")
    angle=None
    if experiment and experiment.angle_id:angle=db.get(CampaignAngle,experiment.angle_id)
    row=Creative(campaign_id=campaign.id,experiment_id=experiment.id if experiment else None,name=data.name or f"Criativo — {campaign.name}",content_type=data.contentType,target_channel=(experiment.target_channel if experiment and experiment.target_channel else data.targetChannel),angle_type_snapshot=angle.angle_type if angle else None,objective_snapshot=campaign.objective,editorial_verdict_snapshot=campaign.editorial_verdict_snapshot,price_verdict_snapshot=campaign.price_verdict_snapshot,content_premise=experiment.hypothesis if experiment else campaign.editorial_positioning,hook=experiment.hook_strategy if experiment else None,cta=experiment.cta_strategy if experiment else campaign.cta_strategy,estimated_duration_seconds=20 if data.contentType=="SHORT_VIDEO" else None,disclosure_text=campaign.disclosure_text,required_warnings=list(campaign.required_warnings or []),forbidden_claims=list(campaign.forbidden_claims or []),generation_mode="MANUAL")
    db.add(row);db.flush();log_decision(db,"OPERATOR","CREATIVE","CREATIVE_CREATED",row.id,metadata={"campaignId":campaign.id,"experimentId":row.experiment_id});db.commit();db.refresh(row);return row
def compliance(db,row):
    scenes=db.scalars(select(CreativeScene).where(CreativeScene.creative_id==row.id)).all();texts=[row.title,row.hook,row.body_script,row.cta]+[x for s in scenes for x in (s.narration_text,s.on_screen_text)];joined=normalize_text(" ".join(x or "" for x in texts));reasons=[]
    for code in row.forbidden_claims or []:
        if any(re.search(pattern,joined) for pattern in CLAIM_PATTERNS.get(code,[])):reasons.append({"code":code,"message":CLAIM_MESSAGES.get(code,"Alegação não permitida detectada.")})
    coverage=[]
    for warning in row.required_warnings or []:
        code=str(warning.get("code",warning.get("message","WARNING")));message=str(warning.get("message",code));covered=message.lower() in joined or any(code in (s.required_warning_codes or []) for s in scenes);coverage.append({"code":code,"message":message,"status":"COVERED" if covered else "MISSING"})
    missing=[x for x in coverage if x["status"]=="MISSING"]
    status="BLOCK" if reasons else "WARN" if missing else "PASS"
    return {"status":status,"reasons":reasons,"requiredWarningCoverage":coverage}
def readiness(db,row):
    comp=compliance(db,row);count=db.scalar(select(func.count()).select_from(CreativeScene).where(CreativeScene.creative_id==row.id)) or 0;campaign=db.get(Campaign,row.campaign_id);checks={"campaignApproved":campaign.status in {"APPROVED","PAUSED","ARCHIVED"},"hook":bool(row.hook),"bodyScript":bool(row.body_script),"cta":bool(row.cta),"sceneCount":count>0,"disclosure":bool(row.disclosure_text),"warningCoverage":not any(x["status"]=="MISSING" for x in comp["requiredWarningCoverage"]),"compliance":comp["status"]=="PASS"}
    state="APPROVED" if row.status=="APPROVED" else "READY_FOR_REVIEW" if all(checks.values()) else "NOT_READY";return {"state":state,"checks":checks,"sceneCount":count,"compliance":comp}
def resolve_content_subject(candidate, campaign):
    generic={"campanha do candidato","nova campanha","campanha","produto","candidato","criativo"}
    values=[getattr(candidate,"working_title",None),getattr(candidate,"source_display_text",None),getattr(campaign,"name",None)]
    for value in values:
        subject=(value or "").strip()
        if not subject or subject.casefold() in generic:continue
        subject=re.sub(r"^teste\s+v[\w.-]+\s*[—–-]\s*","",subject,flags=re.IGNORECASE).strip()
        if subject and subject.casefold() not in generic:return subject
    return "este produto"
def generate_template(db,row,overwrite=False):
    editable(row)
    scene_count=db.scalar(select(func.count()).select_from(CreativeScene).where(CreativeScene.creative_id==row.id)) or 0
    if scene_count and not overwrite:raise HTTPException(409,"Criativo já possui cenas; confirme a substituição para gerar novamente")
    campaign=db.get(Campaign,row.campaign_id);candidate=db.get(CuratorCandidate,campaign.candidate_id)
    product=resolve_content_subject(candidate,campaign)
    angle=row.angle_type_snapshot or "SMART_BUYING";hooks={"SMART_BUYING":f"Vale a pena considerar {product}?","LIMITATION_FIRST":f"Antes de escolher {product}, veja os pontos de atenção.","PRICE_ALERT":f"Vale a pena esperar uma condição melhor para {product}?"};row.hook=hooks.get(angle,f"O que considerar sobre {product}?")
    row.title=f"{product}: vale a pena?";row.content_premise=row.content_premise or f"Apresentar {product} com base nas informações disponíveis e nos pontos de atenção registrados.";row.cta=row.cta or ("Acompanhe e compare antes de decidir." if "BUY_NOW_CTA" in row.forbidden_claims else "Confira os detalhes e decida com informação.");row.estimated_duration_seconds=20;row.generation_mode="DETERMINISTIC_TEMPLATE"
    warnings=list(row.required_warnings or []);warning_codes=[str(w.get("code",w.get("message","WARNING"))) for w in warnings];warning_text=" ".join(str(w.get("message",w.get("code",""))) for w in warnings).strip() or "Considere as limitações e confirme se o produto atende ao seu uso."
    benefit=f"Vamos analisar {product} a partir das informações disponíveis.";conclusion=f"Compare as informações disponíveis sobre {product}, incluindo os pontos de atenção, antes de decidir."
    plan=[("AVATAR","BRUNO","HOOK",row.hook,"QUESTIONING",3,[]),("PRODUCT","NARRATOR","BENEFIT",benefit,None,5,[]),("WARNING","CAROL","LIMITATION",warning_text,"WARNING",4,warning_codes),("PRODUCT","NARRATOR","CONCLUSION",conclusion,None,4,[]),("CTA","BRUNO","CTA",row.cta,"APPROVING",4,[])]
    row.body_script=" ".join(text for _,_,_,text,_,_,_ in plan if text)
    try:
        if scene_count:db.execute(delete(CreativeScene).where(CreativeScene.creative_id==row.id))
        for i,(typ,speaker,purpose,text,state,duration,codes) in enumerate(plan):db.add(CreativeScene(creative_id=row.id,order_index=i,scene_type=typ,speaker=speaker,purpose=purpose,narration_text=text,avatar_state=state,duration_seconds=duration,required_warning_codes=codes))
        log_decision(db,"SYSTEM","CREATIVE","CREATIVE_TEMPLATE_OVERWRITTEN" if scene_count else "CREATIVE_TEMPLATE_GENERATED",row.id,metadata={"angle":angle,"overwrite":bool(scene_count),"replacedSceneCount":scene_count});db.commit();db.refresh(row);return row
    except Exception:
        db.rollback();raise
def submit(db,row):
    if readiness(db,row)["state"]!="READY_FOR_REVIEW":raise HTTPException(409,"Criativo ainda não está pronto para revisão")
    approval=Approval(type="CREATIVE",title=f"Aprovar criativo: {row.name}",description=f"Criativo {row.name}; campanha {row.campaign_id}; formato {row.content_type}; canal {row.target_channel}; pronto somente para futura renderização.",entity_type="CREATIVE",entity_id=row.id,requested_payload={"rendersMedia":False,"publishes":False,"financialSpend":False});db.add(approval);row.status="READY_FOR_REVIEW";log_decision(db,"OPERATOR","CREATIVE","CREATIVE_SUBMITTED",row.id,metadata={"approvalId":approval.id});db.commit();db.refresh(approval);return approval
def variant(db,row,label=None):
    editable(row);group=row.variant_group or str(uuid4());copy=Creative(campaign_id=row.campaign_id,experiment_id=row.experiment_id,name=f"{row.name} — variante",status="DRAFT",content_type=row.content_type,target_channel=row.target_channel,angle_type_snapshot=row.angle_type_snapshot,objective_snapshot=row.objective_snapshot,editorial_verdict_snapshot=row.editorial_verdict_snapshot,price_verdict_snapshot=row.price_verdict_snapshot,title=row.title,content_premise=row.content_premise,hook=row.hook,body_script=row.body_script,cta=row.cta,estimated_duration_seconds=row.estimated_duration_seconds,disclosure_text=row.disclosure_text,required_warnings=list(row.required_warnings or []),forbidden_claims=list(row.forbidden_claims or []),generation_mode=row.generation_mode,variant_group=group,parent_creative_id=row.id,variant_label=label or "variante");row.variant_group=group;db.add(copy);db.flush()
    for s in db.scalars(select(CreativeScene).where(CreativeScene.creative_id==row.id)).all():db.add(CreativeScene(creative_id=copy.id,order_index=s.order_index,scene_type=s.scene_type,speaker=s.speaker,purpose=s.purpose,narration_text=s.narration_text,on_screen_text=s.on_screen_text,visual_instruction=s.visual_instruction,avatar_state=s.avatar_state,duration_seconds=s.duration_seconds,required_warning_codes=list(s.required_warning_codes or [])))
    log_decision(db,"OPERATOR","CREATIVE","CREATIVE_VARIANT_CREATED",copy.id,metadata={"parentCreativeId":row.id,"variantGroup":group});db.commit();db.refresh(copy);return copy

def duplicate(db:Session,row:Creative):
    copy=Creative(campaign_id=row.campaign_id,experiment_id=row.experiment_id,name=f"{row.name} — cópia",status="DRAFT",content_type=row.content_type,target_channel=row.target_channel,angle_type_snapshot=row.angle_type_snapshot,objective_snapshot=row.objective_snapshot,editorial_verdict_snapshot=row.editorial_verdict_snapshot,price_verdict_snapshot=row.price_verdict_snapshot,title=row.title,content_premise=row.content_premise,hook=row.hook,body_script=row.body_script,cta=row.cta,estimated_duration_seconds=row.estimated_duration_seconds,disclosure_text=row.disclosure_text,required_warnings=list(row.required_warnings or []),forbidden_claims=list(row.forbidden_claims or []),generation_mode=row.generation_mode,parent_creative_id=row.id)
    try:
        db.add(copy);db.flush()
        scenes=db.scalars(select(CreativeScene).where(CreativeScene.creative_id==row.id).order_by(CreativeScene.order_index)).all()
        for scene in scenes:db.add(CreativeScene(creative_id=copy.id,order_index=scene.order_index,scene_type=scene.scene_type,speaker=scene.speaker,purpose=scene.purpose,narration_text=scene.narration_text,on_screen_text=scene.on_screen_text,visual_instruction=scene.visual_instruction,avatar_state=scene.avatar_state,duration_seconds=scene.duration_seconds,required_warning_codes=list(scene.required_warning_codes or [])))
        db.flush();log_decision(db,"OPERATOR","CREATIVE","CREATIVE_DUPLICATED",copy.id,metadata={"sourceCreativeId":row.id,"newCreativeId":copy.id,"sceneCount":len(scenes)});db.commit();db.refresh(copy);return copy
    except Exception:
        db.rollback();raise
