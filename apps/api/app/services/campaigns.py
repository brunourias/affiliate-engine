from urllib.parse import urlparse
from fastapi import HTTPException
from sqlalchemy import func,select
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
def objective(verdict):return {"BUY_NOW":"CONVERSION","WORTH_IT":"EDUCATION","WAIT_FOR_BETTER_PRICE":"PRICE_ALERT"}[verdict]
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
def create_from_assessment(db:Session,assessment_id,name):
    a=db.get(CuratorAssessment,assessment_id)
    if not a:raise HTTPException(404,"Assessment não encontrado")
    if a.trust_gate in {"BLOCK","INSUFFICIENT_EVIDENCE"} or a.editorial_verdict not in ALLOWED_VERDICTS:raise HTTPException(409,"Assessment não permite campanha")
    candidate=db.get(CuratorCandidate,a.candidate_id); warnings=list(a.trust_warnings or []); forbidden=["BEST_ON_MARKET_UNSUPPORTED","LOWEST_PRICE_UNVERIFIED","NO_DEFECTS_CLAIM","ONE_HUNDRED_PERCENT_RECOMMENDED"]
    if a.evidence_level!="OWNED_AND_TESTED":forbidden.append("OWN_TEST_CLAIM")
    if a.price_verdict not in {"EXCELLENT_PRICE","GOOD_PRICE"}:forbidden.append("PRICE_PROMOTION_CLAIM")
    if a.price_verdict in {"EXPENSIVE","AVOID_AT_THIS_PRICE","UNKNOWN"} or a.editorial_verdict=="WAIT_FOR_BETTER_PRICE":forbidden.append("BUY_NOW_CTA")
    resolved_name=(candidate.working_title or candidate.source_display_text or "Campanha do candidato") if not name or name.strip().lower() in {"campanha do candidato","nova campanha"} else name.strip()
    row=Campaign(candidate_id=a.candidate_id,assessment_id=a.id,name=resolved_name,objective=objective(a.editorial_verdict),editorial_verdict_snapshot=a.editorial_verdict,trust_gate_snapshot=a.trust_gate,recommendation_score_snapshot=a.recommendation_score,opportunity_score_snapshot=a.opportunity_score,price_verdict_snapshot=a.price_verdict,campaign_priority=priority(a.opportunity_score),disclosure_text=DISCLOSURE,trust_warnings_snapshot=warnings,required_disclosures=[DISCLOSURE],required_warnings=warnings,forbidden_claims=forbidden)
    db.add(row);db.flush();log_decision(db,"OPERATOR","CAMPAIGN","CAMPAIGN_CREATED",row.id,metadata={"assessmentId":a.id});db.commit();db.refresh(row);return row
def readiness(db,row):
    channels=db.scalar(select(func.count()).select_from(CampaignChannel).where(CampaignChannel.campaign_id==row.id,CampaignChannel.enabled==True)) or 0;angles=db.scalar(select(func.count()).select_from(CampaignAngle).where(CampaignAngle.campaign_id==row.id,CampaignAngle.status=="ACTIVE")) or 0;experiments=db.scalar(select(func.count()).select_from(CampaignExperiment).where(CampaignExperiment.campaign_id==row.id)) or 0
    checks={"assessment":bool(row.assessment_id),"trustGate":row.trust_gate_snapshot not in {"BLOCK","INSUFFICIENT_EVIDENCE"},"editorialVerdict":row.editorial_verdict_snapshot in ALLOWED_VERDICTS,"affiliateLink":bool(row.affiliate_url) if row.objective in {"CONVERSION","TRAFFIC"} else True,"disclosure":bool(row.disclosure_text.strip()),"cta":bool(row.cta_strategy),"targetAudience":bool(row.target_audience),"channel":channels>0,"angle":angles>0,"experiment":experiments>0}
    state="APPROVED" if row.status=="APPROVED" else "READY_FOR_APPROVAL" if all(checks.values()) else "NOT_READY"
    return {"state":state,"checks":checks,"channelCount":channels,"angleCount":angles,"experimentCount":experiments}
def submit(db,row):
    if readiness(db,row)["state"]!="READY_FOR_APPROVAL":raise HTTPException(409,"Campanha ainda não está pronta para aprovação")
    if row.status=="PENDING_APPROVAL":raise HTTPException(409,"Campanha já aguarda aprovação")
    channels=db.scalars(select(CampaignChannel).where(CampaignChannel.campaign_id==row.id,CampaignChannel.enabled==True)).all();count=db.scalar(select(func.count()).select_from(CampaignExperiment).where(CampaignExperiment.campaign_id==row.id)) or 0
    opportunity=row.opportunity_score_snapshot if row.opportunity_score_snapshot is not None else "Sem referência suficiente"
    spend="sim — requer aprovação financeira separada" if row.requires_financial_spend else "não"
    approval=Approval(type="CAMPAIGN",title=f"Aprovar campanha: {row.name}",description=f"Campanha/produto: {row.name}; assessment: {row.assessment_id}; Trust Gate: {row.trust_gate_snapshot}; Recommendation Score: {row.recommendation_score_snapshot}; Opportunity Score: {opportunity}; Price Verdict: {row.price_verdict_snapshot}; canais: {', '.join(x.channel for x in channels)}; experimentos: {count}; affiliateLinkPresent: {'sim' if row.affiliate_url else 'não'}; Gasto financeiro: {spend}.",entity_type="CAMPAIGN",entity_id=row.id,requested_payload={"requiresFinancialSpend":row.requires_financial_spend})
    db.add(approval);row.status="PENDING_APPROVAL";log_decision(db,"OPERATOR","CAMPAIGN","CAMPAIGN_SUBMITTED",row.id,metadata={"approvalId":approval.id,"affiliateUrlPresent":bool(row.affiliate_url)});db.commit();db.refresh(approval);return approval
