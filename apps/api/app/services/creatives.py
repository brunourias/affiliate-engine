import re
import unicodedata
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import delete,func,select,update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from apps.api.app.db.models import Creative,CreativeScene,Campaign,CampaignExperiment,CampaignAngle,Approval,CuratorCandidate,CuratorAssessment
from apps.api.app.services.operations import log_decision,utcnow

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
    # Keep any internal callers on the same controlled, idempotent handoff as
    # the public routes; do not retain a weaker legacy creation path.
    from apps.api.app.services.creative_handoff import CreativeHandoffService
    return CreativeHandoffService(db).create(campaign.id,data,experiment.id if experiment else None)
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
    comp=compliance(db,row)
    count=db.scalar(select(func.count()).select_from(CreativeScene).where(CreativeScene.creative_id==row.id)) or 0
    campaign=db.get(Campaign,row.campaign_id)
    from apps.api.app.services.campaigns import readiness as campaign_readiness
    parent=campaign_readiness(db,campaign) if campaign else None
    parent_blockers=list(parent["blockers"]) if parent else []
    blockers=[]
    warnings=[]
    def add(code,message,field=None,**extra):
        item={"code":code,"message":message}
        if field:item["field"]=field
        item.update(extra)
        blockers.append(item)
    if not campaign or campaign.status!="APPROVED":
        add("CAMPAIGN_NOT_APPROVED","A campanha precisa estar aprovada para enviar ou aprovar este criativo.","campaignId")
    if parent_blockers:
        add("CAMPAIGN_CONTEXT_INVALIDATED","O contexto atual da campanha não está mais pronto.","campaignId",parentBlockers=parent_blockers)
    source_approval_valid=True
    source_assessment_valid=True
    if row.creation_source=="CAMPAIGN_APPROVAL":
        source_approval=db.get(Approval,row.source_campaign_approval_id) if row.source_campaign_approval_id else None
        source_approval_valid=bool(source_approval and source_approval.type=="CAMPAIGN" and source_approval.entity_type=="CAMPAIGN" and source_approval.entity_id==row.campaign_id and source_approval.status=="APPROVED")
        assessment=db.get(CuratorAssessment,row.source_assessment_id) if row.source_assessment_id else None
        source_assessment_valid=bool(assessment and campaign and assessment.candidate_id==campaign.candidate_id and row.source_assessment_id==campaign.assessment_id)
        if not source_approval_valid:
            add("SOURCE_CAMPAIGN_APPROVAL_INVALID","A aprovação de origem do criativo não corresponde à campanha atual.","sourceCampaignApprovalId")
        if not source_assessment_valid:
            add("SOURCE_ASSESSMENT_INVALID","A análise de origem do criativo não corresponde à análise aprovada da campanha.","sourceAssessmentId")
    elif not row.creation_source:
        warnings.append({"code":"LEGACY_CREATIVE_ORIGIN_UNTRACKED","message":"A origem deste criativo não foi registrada no fluxo atual."})
    elif row.creation_source not in {None,"CAMPAIGN_APPROVAL"}:
        warnings.append({"code":"LEGACY_CREATIVE_ORIGIN_UNTRACKED","message":"A origem deste criativo não foi registrada no fluxo de aprovação da campanha."})
    if not row.hook or not row.hook.strip():add("HOOK_REQUIRED","Informe um gancho para o criativo.","hook")
    if not row.body_script or not row.body_script.strip():add("BODY_SCRIPT_REQUIRED","Informe o roteiro do criativo.","bodyScript")
    if not row.cta or not row.cta.strip():add("CTA_REQUIRED","Informe a chamada para ação.","cta")
    if count<=0:add("SCENE_REQUIRED","Adicione ao menos uma cena.","scenes")
    if not row.disclosure_text or not row.disclosure_text.strip():add("DISCLOSURE_REQUIRED","Informe o aviso de afiliação.","disclosureText")
    missing_warnings=[item for item in comp["requiredWarningCoverage"] if item["status"]=="MISSING"]
    if missing_warnings:add("WARNING_COVERAGE_REQUIRED","Inclua no conteúdo os avisos obrigatórios.","requiredWarnings",missingWarnings=missing_warnings)
    if comp["status"]=="BLOCK":add("COMPLIANCE_BLOCKED","O conteúdo contém alegações que precisam ser corrigidas.","compliance",reasons=comp["reasons"])
    checks={"campaignApproved":bool(campaign and campaign.status=="APPROVED"),"campaignContextValid":not parent_blockers,"sourceCampaignApprovalValid":source_approval_valid,"sourceAssessmentValid":source_assessment_valid,"hook":bool(row.hook and row.hook.strip()),"bodyScript":bool(row.body_script and row.body_script.strip()),"cta":bool(row.cta and row.cta.strip()),"sceneCount":count>0,"disclosure":bool(row.disclosure_text and row.disclosure_text.strip()),"warningCoverage":not missing_warnings,"compliance":comp["status"]=="PASS"}
    all_ready=not blockers
    state="APPROVED" if row.status=="APPROVED" else "READY_FOR_REVIEW" if all_ready else "NOT_READY"
    if row.status in {"APPROVED","ARCHIVED"}:next_action="NONE"
    elif any(b["code"] in {"CAMPAIGN_NOT_APPROVED","CAMPAIGN_CONTEXT_INVALIDATED","SOURCE_CAMPAIGN_APPROVAL_INVALID","SOURCE_ASSESSMENT_INVALID"} for b in blockers):next_action="REVIEW_CAMPAIGN_CONTEXT"
    elif row.status=="READY_FOR_REVIEW":next_action="AWAITING_APPROVAL"
    elif any(b["code"] in {"COMPLIANCE_BLOCKED","WARNING_COVERAGE_REQUIRED"} for b in blockers):next_action="RESOLVE_COMPLIANCE"
    elif any(b["code"] in {"HOOK_REQUIRED","BODY_SCRIPT_REQUIRED","CTA_REQUIRED"} for b in blockers):next_action="COMPLETE_CONTENT"
    elif any(b["code"]=="SCENE_REQUIRED" for b in blockers):next_action="ADD_SCENE"
    elif row.status in {"DRAFT","REJECTED"} and all_ready:next_action="READY_TO_SUBMIT"
    else:next_action="NONE"
    return {"state":state,"checks":checks,"sceneCount":count,"compliance":comp,"creativeStatus":row.status,"blockers":blockers,"warnings":warnings,"nextAction":next_action}
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
    import time
    def pending_approval():
        rows=list(db.scalars(select(Approval).where(Approval.type=="CREATIVE",Approval.entity_type=="CREATIVE",Approval.entity_id==row.id,Approval.status=="PENDING").order_by(Approval.created_at,Approval.id)))
        if len(rows)==1:return rows[0]
        raise HTTPException(409,{"code":"CREATIVE_APPROVAL_STATE_INCONSISTENT","message":"O estado da aprovação deste criativo precisa ser revisado."})
    if row.status=="READY_FOR_REVIEW":return pending_approval()
    if row.status=="APPROVED":raise HTTPException(409,{"code":"CREATIVE_ALREADY_APPROVED","message":"Este criativo já foi aprovado."})
    if row.status=="ARCHIVED":raise HTTPException(409,{"code":"CREATIVE_ARCHIVED","message":"Um criativo arquivado não pode ser enviado para revisão."})
    if row.status not in {"DRAFT","REJECTED"}:raise HTTPException(409,{"code":"CREATIVE_STATUS_NOT_SUBMITTABLE","message":"O estado atual do criativo não permite envio para revisão."})
    if db.scalar(select(Approval.id).where(Approval.type=="CREATIVE",Approval.entity_type=="CREATIVE",Approval.entity_id==row.id,Approval.status=="PENDING").limit(1)):
        raise HTTPException(409,{"code":"CREATIVE_APPROVAL_STATE_INCONSISTENT","message":"O estado da aprovação deste criativo precisa ser revisado."})
    current=readiness(db,row)
    if current["blockers"]:raise HTTPException(409,{"code":"CREATIVE_NOT_READY","message":"O criativo ainda não está pronto para revisão.","blockers":current["blockers"]})
    creative_id=row.id
    try:
        acquired=db.execute(update(Creative).where(Creative.id==creative_id,Creative.status.in_(["DRAFT","REJECTED"])).values(status="READY_FOR_REVIEW",updated_at=utcnow())).rowcount
        if acquired!=1:
            db.rollback()
            current_row=db.get(Creative,creative_id)
            if current_row and current_row.status=="READY_FOR_REVIEW":return pending_approval()
            if current_row and current_row.status=="APPROVED":raise HTTPException(409,{"code":"CREATIVE_ALREADY_APPROVED","message":"Este criativo já foi aprovado."})
            if current_row and current_row.status=="ARCHIVED":raise HTTPException(409,{"code":"CREATIVE_ARCHIVED","message":"Um criativo arquivado não pode ser enviado para revisão."})
            raise HTTPException(409,{"code":"CREATIVE_STATUS_NOT_SUBMITTABLE","message":"O estado do criativo mudou. Atualize e tente novamente."})
        db.expire(row);row=db.get(Creative,creative_id)
        scenes=list(db.scalars(select(CreativeScene).where(CreativeScene.creative_id==creative_id).order_by(CreativeScene.order_index,CreativeScene.id)))
        campaign=db.get(Campaign,row.campaign_id)
        experiment=db.get(CampaignExperiment,row.experiment_id) if row.experiment_id else None
        current_comp=compliance(db,row)
        description=(f"Criativo: {row.name}\nCampanha: {campaign.name if campaign else row.campaign_id}\nExperimento: {experiment.hypothesis if experiment else 'Não informado'}\nFormato: {row.content_type}\nCanal: {row.target_channel}\nTítulo: {row.title or 'Não informado'}\nPremissa: {row.content_premise or 'Não informada'}\nHook: {row.hook or 'Não informado'}\nRoteiro: {row.body_script or 'Não informado'}\nCTA: {row.cta or 'Não informado'}\nCenas: {len(scenes)}\nAviso de afiliação: {row.disclosure_text or 'Não informado'}\nCompliance: {current_comp['status']}\nAdvertências: {row.required_warnings or []}\nAlegações proibidas: {row.forbidden_claims or []}\nModo de geração: {row.generation_mode}\nAprovação de origem da campanha: {row.source_campaign_approval_id or 'Não informada'}\nAnálise de origem: {row.source_assessment_id or 'Não informada'}")
        approval=Approval(type="CREATIVE",title=f"Aprovar criativo: {row.name}",description=description,entity_type="CREATIVE",entity_id=row.id,requested_payload={"rendersMedia":False,"publishes":False,"financialSpend":False,"campaignId":row.campaign_id,"experimentId":row.experiment_id,"sceneCount":len(scenes),"complianceStatus":current_comp["status"]})
        db.add(approval);db.flush()
        log_decision(db,"OPERATOR","CREATIVE","CREATIVE_SUBMITTED",row.id,metadata={"creativeId":row.id,"campaignId":row.campaign_id,"experimentId":row.experiment_id,"approvalId":approval.id,"readinessState":current["state"],"sceneCount":len(scenes),"complianceStatus":current_comp["status"],"sourceCampaignApprovalId":row.source_campaign_approval_id,"sourceAssessmentId":row.source_assessment_id})
        db.commit();db.refresh(approval);return approval
    except OperationalError:
        db.rollback()
        for _ in range(10):
            current_row=db.get(Creative,creative_id)
            if current_row and current_row.status=="READY_FOR_REVIEW":
                try:return pending_approval()
                except HTTPException:pass
            time.sleep(0.02)
        raise HTTPException(409,{"code":"CREATIVE_APPROVAL_STATE_INCONSISTENT","message":"Não foi possível confirmar o envio concorrente. Atualize o estado e tente novamente."})
    except Exception:
        db.rollback();raise
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
