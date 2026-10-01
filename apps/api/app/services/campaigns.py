from urllib.parse import urlparse
from fastapi import HTTPException
from sqlalchemy import func,select,update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from apps.api.app.db.models import Campaign,CampaignChannel,CampaignAngle,CampaignExperiment,CuratorAssessment,CuratorCandidate,Approval
from apps.api.app.services.operations import log_decision,utcnow
DISCLOSURE="Este conteúdo pode conter link de afiliado. Podemos receber comissão pela compra, sem custo adicional para você."
ALLOWED_VERDICTS={"BUY_NOW","WORTH_IT","WAIT_FOR_BETTER_PRICE"}
def priority(score):
    if score is None:return "UNKNOWN"
    if score>=80:return "VERY_HIGH"
    if score>=65:return "HIGH"
    if score>=45:return "MEDIUM"
    return "LOW"
def objective(verdict):return {"BUY_NOW":"CONVERSION","WORTH_IT":"EDUCATION","WAIT_FOR_BETTER_PRICE":"PRICE_ALERT"}.get(verdict,"DISCOVERY")
def validate_url(value):
    if value is None or value=="":return None
    p=urlparse(value)
    if p.scheme not in {"http","https"} or not p.netloc:raise HTTPException(422,"URL de afiliado inválida")
    return value
def campaign_or_404(db,id):
    row=db.get(Campaign,id)
    if not row:raise HTTPException(404,"Campanha não encontrada")
    return row
def editable(row):
    if row.status in {"PENDING_APPROVAL","APPROVED","PAUSED","ARCHIVED"}:raise HTTPException(409,"Campanha enviada para aprovação ou já aprovada não pode ser editada")
class CampaignCreationService:
    """Creates a DRAFT only from the current, explicitly approved handoff."""
    def __init__(self, db: Session): self.db = db

    def _current(self, candidate):
        return self.db.scalar(select(CuratorAssessment).where(CuratorAssessment.candidate_id == candidate.id).order_by(CuratorAssessment.assessment_version.desc()))

    def create(self, candidate_id: str, name: str | None = None):
        candidate=self.db.get(CuratorCandidate,candidate_id)
        if not candidate: raise HTTPException(404,"Candidato não encontrado")
        if candidate.status=="ARCHIVED": raise HTTPException(409,"CANDIDATE_ARCHIVED")
        if candidate.opportunity_review_status!="COMMERCIAL_REVIEW": raise HTTPException(409,"CAMPAIGN_HANDOFF_REQUIRED")
        if candidate.commercial_analysis_status!="ASSESSMENT_AVAILABLE": raise HTTPException(409,"ASSESSMENT_NOT_AVAILABLE")
        current=self._current(candidate)
        if not current: raise HTTPException(409,"ASSESSMENT_NOT_AVAILABLE")
        if candidate.campaign_handoff_status!="APPROVED": raise HTTPException(409,"CAMPAIGN_HANDOFF_REQUIRED")
        if candidate.campaign_handoff_assessment_id != current.id: raise HTTPException(409,"CAMPAIGN_HANDOFF_STALE")
        existing=list(self.db.scalars(select(Campaign).where(Campaign.assessment_id==current.id)))
        if len(existing)==1: return {"created":False,"campaign":existing[0]}
        if len(existing)>1: raise HTTPException(409,"MULTIPLE_CAMPAIGNS_FOR_ASSESSMENT")
        return self._create(candidate,current,name)

    def state(self, candidate_id: str) -> dict:
        """Read-only state for the current handoff assessment and its campaign."""
        candidate=self.db.get(CuratorCandidate,candidate_id)
        if not candidate: raise HTTPException(404,"Candidato não encontrado")
        current=self._current(candidate)
        base={"campaignId":None,"campaignName":None,"campaignStatus":None,"assessmentId":current.id if current else None,"assessmentVersion":current.assessment_version if current else None,"reasonCode":None}
        reason=None
        if candidate.status=="ARCHIVED": reason="CANDIDATE_ARCHIVED"
        elif candidate.opportunity_review_status!="COMMERCIAL_REVIEW": reason="CAMPAIGN_HANDOFF_REQUIRED"
        elif candidate.commercial_analysis_status!="ASSESSMENT_AVAILABLE" or current is None: reason="ASSESSMENT_NOT_AVAILABLE"
        elif candidate.campaign_handoff_status!="APPROVED": reason="CAMPAIGN_HANDOFF_REQUIRED"
        elif candidate.campaign_handoff_assessment_id!=current.id: reason="CAMPAIGN_HANDOFF_STALE"
        if reason:
            return {"state":"NOT_ELIGIBLE",**base,"reasonCode":reason}
        existing=list(self.db.scalars(select(Campaign).where(Campaign.assessment_id==current.id).order_by(Campaign.created_at,Campaign.id)))
        if len(existing)>1:
            return {"state":"MULTIPLE_CAMPAIGNS","reasonCode":"MULTIPLE_CAMPAIGNS_FOR_ASSESSMENT",**base}
        if len(existing)==1:
            campaign=existing[0]
            return {"state":"CAMPAIGN_EXISTS","campaignId":campaign.id,"campaignName":campaign.name,"campaignStatus":campaign.status,"assessmentId":current.id,"assessmentVersion":current.assessment_version,"reasonCode":None}
        return {"state":"READY_TO_CREATE",**base}

    def _create(self,candidate,a,name):
        warnings=list(a.trust_warnings or []); forbidden=["BEST_ON_MARKET_UNSUPPORTED","LOWEST_PRICE_UNVERIFIED","NO_DEFECTS_CLAIM","ONE_HUNDRED_PERCENT_RECOMMENDED"]
        if a.evidence_level!="OWNED_AND_TESTED":forbidden.append("OWN_TEST_CLAIM")
        if a.price_verdict not in {"EXCELLENT_PRICE","GOOD_PRICE"}:forbidden.append("PRICE_PROMOTION_CLAIM")
        if a.price_verdict in {"EXPENSIVE","AVOID_AT_THIS_PRICE","UNKNOWN"} or a.editorial_verdict=="WAIT_FOR_BETTER_PRICE":forbidden.append("BUY_NOW_CTA")
        resolved_name=(candidate.working_title or candidate.source_display_text or "Campanha do candidato") if not name or not name.strip() else name.strip()
        key=f"CAMPAIGN_HANDOFF:{a.id}"
        row=Campaign(candidate_id=a.candidate_id,assessment_id=a.id,name=resolved_name,status="DRAFT",objective=objective(a.editorial_verdict),editorial_verdict_snapshot=a.editorial_verdict,trust_gate_snapshot=a.trust_gate,recommendation_score_snapshot=a.recommendation_score,opportunity_score_snapshot=a.opportunity_score,price_verdict_snapshot=a.price_verdict,campaign_priority=priority(a.opportunity_score),disclosure_text=DISCLOSURE,trust_warnings_snapshot=warnings,required_disclosures=[DISCLOSURE],required_warnings=warnings,forbidden_claims=forbidden,creation_source="CAMPAIGN_HANDOFF",creation_key=key)
        try:
            self.db.add(row); self.db.flush()
            log_decision(self.db,"OPERATOR","CAMPAIGN","CAMPAIGN_CREATED",row.id,metadata={"creationSource":"CAMPAIGN_HANDOFF","candidateId":candidate.id,"assessmentId":a.id,"assessmentVersion":a.assessment_version,"campaignHandoffReviewedAt":candidate.campaign_handoff_reviewed_at.isoformat() if candidate.campaign_handoff_reviewed_at else None})
            self.db.commit(); self.db.refresh(row); return {"created":True,"campaign":row}
        except IntegrityError:
            self.db.rollback(); existing=self.db.scalar(select(Campaign).where(Campaign.creation_key==key))
            if existing: return {"created":False,"campaign":existing}
            raise
        except Exception:
            self.db.rollback()
            raise

def create_from_assessment(db:Session,assessment_id,name):
    assessment=db.get(CuratorAssessment,assessment_id)
    if not assessment: raise HTTPException(404,"Assessment não encontrado")
    return CampaignCreationService(db).create(assessment.candidate_id,name)["campaign"]
BLOCKER_MESSAGES={
    "ASSESSMENT_REQUIRED":("A análise de origem não está disponível.","assessment"),
    "ASSESSMENT_OUTDATED":("A análise comercial mudou depois da criação desta campanha.","assessmentId"),
    "TRUST_GATE_BLOCKED":("A qualidade das evidências não permite avançar.","trustGateSnapshot"),
    "INSUFFICIENT_EVIDENCE":("Ainda não há evidências suficientes para avançar.","trustGateSnapshot"),
    "EDITORIAL_VERDICT_NOT_ELIGIBLE":("A conclusão editorial não permite esta campanha.","editorialVerdictSnapshot"),
    "TARGET_AUDIENCE_REQUIRED":("Informe o público-alvo.","targetAudience"),
    "EDITORIAL_POSITIONING_REQUIRED":("Defina o posicionamento editorial.","editorialPositioning"),
    "PRIMARY_MESSAGE_REQUIRED":("Defina a mensagem principal.","primaryMessage"),
    "CTA_REQUIRED":("Defina uma chamada para ação.","ctaStrategy"),
    "DISCLOSURE_REQUIRED":("Informe o disclosure obrigatório.","disclosureText"),
    "AFFILIATE_LINK_REQUIRED":("Configure um link de afiliado para este objetivo.","affiliateUrl"),
    "AFFILIATE_LINK_NOT_VERIFIED":("Verifique o link de afiliado antes de enviar.","affiliateUrl"),
    "CHANNEL_REQUIRED":("Adicione ao menos um canal ativo.","channels"),
    "ANGLE_REQUIRED":("Adicione ao menos um ângulo ativo.","angles"),
    "EXPERIMENT_REQUIRED":("Adicione ao menos um experimento válido.","experiments"),
}
BLOCKER_ORDER=tuple(BLOCKER_MESSAGES)
FINANCIAL_APPROVAL_REQUIRED={"code":"FINANCIAL_APPROVAL_REQUIRED","message":"Qualquer gasto financeiro exigirá autorização separada antes da execução."}
def _present(value): return isinstance(value,str) and bool(value.strip())
def _valid_link(value):
    if not _present(value): return False
    parsed=urlparse(value.strip())
    return parsed.scheme in {"http","https"} and bool(parsed.netloc)
def readiness(db,row):
    """Read-only, explainable Campaign readiness; never writes logs or state."""
    channels=list(db.scalars(select(CampaignChannel).where(CampaignChannel.campaign_id==row.id,CampaignChannel.enabled==True).order_by(CampaignChannel.channel,CampaignChannel.id)))
    angles=list(db.scalars(select(CampaignAngle).where(CampaignAngle.campaign_id==row.id,CampaignAngle.status=="ACTIVE").order_by(CampaignAngle.priority.desc(),CampaignAngle.id)))
    all_experiments=list(db.scalars(select(CampaignExperiment).where(CampaignExperiment.campaign_id==row.id).order_by(CampaignExperiment.created_at,CampaignExperiment.id)))
    experiments=[]
    enabled_channels={channel.channel for channel in channels}
    for experiment in all_experiments:
        # PLANNED is the only active CampaignExperiment lifecycle state currently
        # used by the domain. Explicitly disabled/cancelled and unknown states do
        # not satisfy readiness.
        if experiment.status!="PLANNED": continue
        if experiment.angle_id and not db.scalar(select(CampaignAngle.id).where(CampaignAngle.id==experiment.angle_id,CampaignAngle.campaign_id==row.id)): continue
        if experiment.target_channel and experiment.target_channel not in enabled_channels: continue
        experiments.append(experiment)
    source=db.get(CuratorAssessment,row.assessment_id) if row.assessment_id else None
    candidate=db.get(CuratorCandidate,row.candidate_id)
    latest=(db.scalar(select(CuratorAssessment).where(CuratorAssessment.candidate_id==row.candidate_id).order_by(CuratorAssessment.assessment_version.desc(),CuratorAssessment.created_at.desc(),CuratorAssessment.id.desc())) if candidate else None)
    source_current=bool(source and source.candidate_id==row.candidate_id and latest and latest.id==source.id)
    trust_ok=row.trust_gate_snapshot not in {"BLOCK","INSUFFICIENT_EVIDENCE"}
    verdict_ok=row.editorial_verdict_snapshot in ALLOWED_VERDICTS
    link_present=_present(row.affiliate_url)
    link_required=row.objective in {"CONVERSION","TRAFFIC"}
    link_valid=_valid_link(row.affiliate_url) if link_present else not link_required
    link_verified=bool(row.affiliate_url_verified_at) if link_present else not link_required
    checks={
        "assessment":bool(source and source.candidate_id==row.candidate_id),
        "sourceAssessmentCurrent":source_current,
        "trustGate":trust_ok,
        "editorialVerdict":verdict_ok,
        "affiliateLink":link_valid,
        "affiliateLinkVerified":link_verified,
        "disclosure":_present(row.disclosure_text),
        "cta":_present(row.cta_strategy),
        "targetAudience":_present(row.target_audience),
        "editorialPositioning":_present(row.editorial_positioning),
        "primaryMessage":_present(row.primary_message),
        "channel":bool(channels),
        "angle":bool(angles),
        "experiment":bool(experiments),
    }
    failed=[]
    if not checks["assessment"]: failed.append("ASSESSMENT_REQUIRED")
    elif not source_current: failed.append("ASSESSMENT_OUTDATED")
    if not trust_ok: failed.append("INSUFFICIENT_EVIDENCE" if row.trust_gate_snapshot=="INSUFFICIENT_EVIDENCE" else "TRUST_GATE_BLOCKED")
    if not verdict_ok: failed.append("EDITORIAL_VERDICT_NOT_ELIGIBLE")
    for check,code in (("targetAudience","TARGET_AUDIENCE_REQUIRED"),("editorialPositioning","EDITORIAL_POSITIONING_REQUIRED"),("primaryMessage","PRIMARY_MESSAGE_REQUIRED"),("cta","CTA_REQUIRED"),("disclosure","DISCLOSURE_REQUIRED")):
        if not checks[check]: failed.append(code)
    if link_required and not link_present: failed.append("AFFILIATE_LINK_REQUIRED")
    elif link_present and not link_valid: failed.append("AFFILIATE_LINK_REQUIRED")
    elif link_present and not link_verified: failed.append("AFFILIATE_LINK_NOT_VERIFIED")
    for check,code in (("channel","CHANNEL_REQUIRED"),("angle","ANGLE_REQUIRED"),("experiment","EXPERIMENT_REQUIRED")):
        if not checks[check]: failed.append(code)
    blockers=[{"code":code,"message":BLOCKER_MESSAGES[code][0],"field":BLOCKER_MESSAGES[code][1]} for code in BLOCKER_ORDER if code in failed]
    warnings=[dict(FINANCIAL_APPROVAL_REQUIRED)] if row.requires_financial_spend else []
    ready=not blockers
    lifecycle={"PENDING_APPROVAL":"PENDING_APPROVAL","APPROVED":"APPROVED","PAUSED":"PAUSED","ARCHIVED":"ARCHIVED"}
    if row.status in lifecycle: state=lifecycle[row.status]
    elif row.status=="REJECTED" and not ready: state="REJECTED"
    else: state="READY_FOR_APPROVAL" if ready else "NOT_READY"
    if row.status=="PENDING_APPROVAL": next_action="AWAITING_APPROVAL"
    elif row.status in {"APPROVED","PAUSED","ARCHIVED"}: next_action="NONE"
    elif "ASSESSMENT_OUTDATED" in failed: next_action="REVIEW_UPDATED_ASSESSMENT"
    elif "ASSESSMENT_REQUIRED" in failed or not trust_ok or not verdict_ok: next_action="RESOLVE_EVIDENCE"
    elif any(code in failed for code in ("TARGET_AUDIENCE_REQUIRED","EDITORIAL_POSITIONING_REQUIRED","PRIMARY_MESSAGE_REQUIRED","CTA_REQUIRED","DISCLOSURE_REQUIRED")): next_action="COMPLETE_STRATEGY"
    elif "AFFILIATE_LINK_REQUIRED" in failed: next_action="CONFIGURE_AFFILIATE_LINK"
    elif "AFFILIATE_LINK_NOT_VERIFIED" in failed: next_action="VERIFY_AFFILIATE_LINK"
    elif "CHANNEL_REQUIRED" in failed: next_action="ADD_CHANNEL"
    elif "ANGLE_REQUIRED" in failed: next_action="ADD_ANGLE"
    elif "EXPERIMENT_REQUIRED" in failed: next_action="ADD_EXPERIMENT"
    elif ready: next_action="READY_TO_SUBMIT"
    else: next_action="NONE"
    return {"state":state,"campaignStatus":row.status,"checks":checks,"blockers":blockers,"warnings":warnings,"nextAction":next_action,"channelCount":len(channels),"angleCount":len(angles),"experimentCount":len(experiments)}
def _pending_campaign_approval(db,row):
    approvals=list(db.scalars(select(Approval).where(Approval.type=="CAMPAIGN",Approval.entity_type=="CAMPAIGN",Approval.entity_id==row.id,Approval.status=="PENDING").order_by(Approval.created_at,Approval.id)))
    if len(approvals)!=1:
        raise HTTPException(409,{"code":"CAMPAIGN_APPROVAL_STATE_INCONSISTENT","message":"O estado da aprovação desta campanha precisa ser revisado."})
    return approvals[0]
def _approval_description(row,channels,count):
    opportunity=row.opportunity_score_snapshot if row.opportunity_score_snapshot is not None else "Sem referência suficiente"
    audience=row.target_audience or "Não informado";positioning=row.editorial_positioning or "Não informado";message=row.primary_message or "Não informado";cta=row.cta_strategy or "Não informado"
    return (f"Campanha: {row.name}\nAnálise: {row.assessment_id}\nQualidade das evidências: {row.trust_gate_snapshot}\nConclusão editorial: {row.editorial_verdict_snapshot}\nRecommendation Score: {row.recommendation_score_snapshot if row.recommendation_score_snapshot is not None else 'Não informado'}\nOpportunity Score: {opportunity}\nPrice Verdict: {row.price_verdict_snapshot}\nObjetivo: {row.objective}\nPúblico: {audience}\nPosicionamento: {positioning}\nMensagem principal: {message}\nCTA: {cta}\nDisclosure: {row.disclosure_text or 'Não informado'}\nCanais: {', '.join(x.channel for x in channels) or 'Nenhum'}\nExperimentos: {count}\nLink de afiliado: {'configurado e verificado' if row.affiliate_url and row.affiliate_url_verified_at else 'configurado, não verificado' if row.affiliate_url else 'não configurado'}\nGasto financeiro necessário: {'sim; exige autorização separada' if row.requires_financial_spend else 'não'}")
def submit(db,row):
    current=readiness(db,row)
    if row.status=="PENDING_APPROVAL": return _pending_campaign_approval(db,row)
    if row.status=="APPROVED": raise HTTPException(409,{"code":"CAMPAIGN_ALREADY_APPROVED","message":"Esta campanha já foi aprovada."})
    if row.status=="ARCHIVED": raise HTTPException(409,{"code":"CAMPAIGN_ARCHIVED","message":"Uma campanha arquivada não pode ser enviada para aprovação."})
    if row.status=="PAUSED": raise HTTPException(409,{"code":"CAMPAIGN_PAUSED","message":"Uma campanha pausada não pode ser enviada para aprovação."})
    if row.status not in {"DRAFT","REJECTED"}: raise HTTPException(409,{"code":"CAMPAIGN_STATUS_NOT_SUBMITTABLE","message":"O estado atual da campanha não permite envio para aprovação."})
    if current["state"]!="READY_FOR_APPROVAL": raise HTTPException(409,{"code":"CAMPAIGN_NOT_READY","message":"A campanha ainda não está pronta para aprovação.","blockers":current["blockers"]})
    # Conditional transition is the single-writer gate: only one request can create
    # the pending Approval and its DecisionLog for this draft/rejected revision.
    acquired=db.execute(update(Campaign).where(Campaign.id==row.id,Campaign.status.in_(["DRAFT","REJECTED"])).values(status="PENDING_APPROVAL",updated_at=utcnow())).rowcount
    if acquired!=1:
        db.expire(row);row=db.get(Campaign,row.id)
        if row and row.status=="PENDING_APPROVAL": return _pending_campaign_approval(db,row)
        if row and row.status=="APPROVED": raise HTTPException(409,{"code":"CAMPAIGN_ALREADY_APPROVED","message":"Esta campanha já foi aprovada."})
        raise HTTPException(409,{"code":"CAMPAIGN_STATUS_NOT_SUBMITTABLE","message":"O estado da campanha mudou. Atualize e tente novamente."})
    db.refresh(row)
    channels=list(db.scalars(select(CampaignChannel).where(CampaignChannel.campaign_id==row.id,CampaignChannel.enabled==True).order_by(CampaignChannel.channel)))
    count=db.scalar(select(func.count()).select_from(CampaignExperiment).where(CampaignExperiment.campaign_id==row.id)) or 0
    approval=Approval(type="CAMPAIGN",title=f"Aprovar campanha: {row.name}",description=_approval_description(row,channels,count),entity_type="CAMPAIGN",entity_id=row.id,requested_payload={"requiresFinancialSpend":row.requires_financial_spend})
    try:
        db.add(approval);db.flush()
        log_decision(db,"OPERATOR","CAMPAIGN","CAMPAIGN_SUBMITTED",row.id,metadata={"campaignId":row.id,"assessmentId":row.assessment_id,"readinessState":current["state"],"approvalId":approval.id,"requiresFinancialSpend":row.requires_financial_spend,"channelCount":len(channels),"angleCount":current["angleCount"],"experimentCount":current["experimentCount"]})
        db.commit();db.refresh(approval);return approval
    except Exception:
        db.rollback();raise
