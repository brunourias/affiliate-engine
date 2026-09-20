from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from apps.api.app.db.session import get_db
from apps.api.app.db.models import AppSettings, Approval, Notification, AgentTask, DecisionLog, MarketplaceCapability, MarketplaceCategory, RadarRun, RadarSignal, CuratorCandidate, CuratorEvidence, CuratorAssessment,Campaign,CampaignChannel,CampaignAngle,CampaignExperiment,Creative,CreativeScene
from apps.api.app.integrations.mercado_livre import MercadoLivreDiagnostics, MercadoLivreRadar, RadarDomainError
from apps.api.app.schemas import *
from apps.api.app.services.operations import *
from apps.api.app.services.curator import EVIDENCE_TYPES, checklist, from_radar, parse_mlb, refresh, stale
from apps.api.app.services.assessment import CuratorAssessmentService
from apps.api.app.services.campaigns import campaign_or_404,create_from_assessment,editable,readiness,submit,validate_url,utcnow
from apps.api.app.services import creatives as creative_service
router=APIRouter()
@router.get("/health")
def health(db:Session=Depends(get_db)):
    db.execute(select(1)); s=settings_row(db)
    return {"status":"healthy","frontend":"separate","backend":"operational","database":"operational","migrations":"current","scheduler":"operational","automationEnabled":s.system_automation_enabled,"futureIntegrations":"not_configured","timestamp":utcnow()}
@router.get("/settings",response_model=SettingsOut)
def get_settings(db:Session=Depends(get_db)): return settings_row(db)
@router.patch("/settings",response_model=SettingsOut)
def patch_settings(data:SettingsPatch,db:Session=Depends(get_db)):
    s=settings_row(db); changed={}; mapping={"monthlyConfirmedCommissionGoalCents":"monthly_confirmed_commission_goal_cents","dailyPublicationLimit":"daily_publication_limit","systemAutomationEnabled":"system_automation_enabled","radarEnabled":"radar_enabled","creativeEnabled":"creative_enabled","publishingEnabled":"publishing_enabled","commentReplyEnabled":"comment_reply_enabled","externalIntelligenceEnabled":"external_intelligence_enabled","timezone":"timezone"}
    for key,value in data.model_dump(exclude_none=True).items():
        attr=mapping[key]
        if getattr(s,attr)!=value: changed[key]={"from":getattr(s,attr),"to":value}; setattr(s,attr,value)
    if changed: log_decision(db,"OPERATOR","APP_SETTINGS","SETTINGS_UPDATED",reason="Configurações alteradas",metadata={"changes":changed})
    db.commit(); db.refresh(s); return s
@router.post("/automation/pause",response_model=SettingsOut)
def pause(db:Session=Depends(get_db)):
    s=settings_row(db)
    if s.system_automation_enabled: s.system_automation_enabled=False; log_decision(db,"OPERATOR","SYSTEM","AUTOMATION_PAUSED",reason="Kill Switch acionado"); notify(db,"CRITICAL","Automação interrompida","O Kill Switch foi acionado. Nenhuma tarefa automática será iniciada.","AUTOMATION"); db.commit(); db.refresh(s)
    return s
@router.post("/automation/resume",response_model=SettingsOut)
def resume(db:Session=Depends(get_db)):
    s=settings_row(db)
    if not s.system_automation_enabled: s.system_automation_enabled=True; log_decision(db,"OPERATOR","SYSTEM","AUTOMATION_RESUMED",reason="Automação reativada; fila seguirá limites normais"); notify(db,"SUCCESS","Automação reativada","O scheduler voltou ao comportamento normal; a fila não será disparada em massa.","AUTOMATION"); db.commit(); db.refresh(s)
    return s
@router.get("/approvals",response_model=list[ApprovalOut])
def approvals(status:str|None=None,type:str|None=None,db:Session=Depends(get_db)):
    q=select(Approval).order_by(Approval.created_at.desc()); q=q.where(Approval.status==status) if status else q; q=q.where(Approval.type==type) if type else q; return db.scalars(q).all()
@router.get("/approvals/{item_id}",response_model=ApprovalOut)
def approval(item_id:str,db:Session=Depends(get_db)):
    item=db.get(Approval,item_id)
    if not item: raise HTTPException(404,"Aprovação não encontrada")
    return item
@router.post("/approvals/{item_id}/approve",response_model=ApprovalOut)
def approve(item_id:str,data:DecisionRequest,db:Session=Depends(get_db)):
    item=db.get(Approval,item_id)
    if not item: raise HTTPException(404,"Aprovação não encontrada")
    return decide(db,item,"APPROVED",data.reason)
@router.post("/approvals/{item_id}/reject",response_model=ApprovalOut)
def reject(item_id:str,data:DecisionRequest,db:Session=Depends(get_db)):
    item=db.get(Approval,item_id)
    if not item: raise HTTPException(404,"Aprovação não encontrada")
    return decide(db,item,"REJECTED",data.reason)
@router.get("/notifications",response_model=list[NotificationOut])
def notifications(unread:bool|None=None,db:Session=Depends(get_db)):
    q=select(Notification).order_by(Notification.created_at.desc()); q=q.where(Notification.is_read==False) if unread else q; return db.scalars(q).all()
@router.post("/notifications/{item_id}/read",response_model=NotificationOut)
def read_notification(item_id:str,db:Session=Depends(get_db)):
    item=db.get(Notification,item_id)
    if not item: raise HTTPException(404,"Notificação não encontrada")
    if not item.is_read: item.is_read=True; item.read_at=utcnow(); db.commit(); db.refresh(item)
    return item
@router.post("/notifications/read-all")
def read_all(db:Session=Depends(get_db)):
    items=db.scalars(select(Notification).where(Notification.is_read==False)).all(); now=utcnow()
    for item in items: item.is_read=True; item.read_at=now
    db.commit(); return {"updated":len(items)}
@router.get("/decisions",response_model=list[DecisionOut])
def decisions(actor:str|None=None,entityType:str|None=None,order:Literal["asc","desc"]="desc",db:Session=Depends(get_db)):
    q=select(DecisionLog); q=q.where(DecisionLog.actor==actor) if actor else q; q=q.where(DecisionLog.entity_type==entityType) if entityType else q; q=q.order_by(DecisionLog.timestamp.asc() if order=="asc" else DecisionLog.timestamp.desc()); return db.scalars(q).all()
@router.get("/tasks",response_model=list[TaskOut])
def tasks(status:str|None=None,db:Session=Depends(get_db)):
    q=select(AgentTask).order_by(AgentTask.created_at.desc()); q=q.where(AgentTask.status==status) if status else q; return db.scalars(q).all()
@router.post("/tasks",response_model=TaskOut,status_code=201)
def create_task(data:TaskCreate,db:Session=Depends(get_db)):
    task=AgentTask(type=data.type,title=data.title,payload=data.payload,is_automatic=data.isAutomatic); db.add(task); db.flush(); log_decision(db,"OPERATOR","AGENT_TASK","TASK_CREATED",task.id,metadata={"automatic":task.is_automatic,"type":task.type}); db.commit(); db.refresh(task); return task
@router.post("/tasks/{item_id}/run",response_model=TaskOut)
def run(item_id:str,db:Session=Depends(get_db)):
    task=db.get(AgentTask,item_id)
    if not task: raise HTTPException(404,"Tarefa não encontrada")
    return run_task(db,task)
@router.post("/tasks/{item_id}/cancel",response_model=TaskOut)
def cancel(item_id:str,db:Session=Depends(get_db)):
    task=db.get(AgentTask,item_id)
    if not task: raise HTTPException(404,"Tarefa não encontrada")
    return transition(db,task,"CANCELED")
@router.get("/dashboard")
def dashboard(db:Session=Depends(get_db)):
    s=settings_row(db); tasks=db.scalars(select(AgentTask).order_by(AgentTask.updated_at.desc())).all(); approvals=db.scalars(select(Approval).order_by(Approval.created_at.desc()).limit(5)).all(); notes=db.scalars(select(Notification).order_by(Notification.created_at.desc()).limit(5)).all(); decisions=db.scalars(select(DecisionLog).order_by(DecisionLog.timestamp.desc()).limit(5)).all()
    return {"settings":SettingsOut.model_validate(s),"commission":{"confirmedCents":0,"goalCents":s.monthly_confirmed_commission_goal_cents,"sourceConnected":False},"agent":{"status":"PAUSED" if not s.system_automation_enabled else "AVAILABLE","currentTask":next((TaskOut.model_validate(t) for t in tasks if t.status=="RUNNING"),None),"pending":sum(t.status=="PENDING" for t in tasks),"failed":sum(t.status=="FAILED" for t in tasks),"lastExecution":next((t.finished_at for t in tasks if t.finished_at),None)},"approvals":[ApprovalOut.model_validate(x) for x in approvals],"notifications":[NotificationOut.model_validate(x) for x in notes],"decisions":[DecisionOut.model_validate(x) for x in decisions],"unreadNotifications":db.scalar(select(func.count()).select_from(Notification).where(Notification.is_read==False)),"pendingApprovals":db.scalar(select(func.count()).select_from(Approval).where(Approval.status=="PENDING"))}


@router.get("/marketplaces/mercado-livre", response_model=MarketplaceConnectionOut)
def mercado_livre_connection(db: Session = Depends(get_db)):
    service = MercadoLivreDiagnostics(db)
    try:
        connection = service.connection(); service.ensure_capabilities(); db.commit(); db.refresh(connection)
        return connection
    finally:
        service.close()


@router.get("/marketplaces/mercado-livre/capabilities", response_model=list[MarketplaceCapabilityOut])
def mercado_livre_capabilities(db: Session = Depends(get_db)):
    service = MercadoLivreDiagnostics(db)
    try:
        service.ensure_capabilities()
        return db.scalars(select(MarketplaceCapability).order_by(MarketplaceCapability.capability_key)).all()
    finally:
        service.close()


@router.post("/marketplaces/mercado-livre/diagnostics", response_model=MarketplaceConnectionOut)
def run_mercado_livre_diagnostics(data: MarketplaceDiagnosticsRequest, db: Session = Depends(get_db)):
    service = MercadoLivreDiagnostics(db)
    try:
        return service.run(data.categoryId)
    finally:
        service.close()


@router.post("/marketplaces/mercado-livre/diagnostics/item", response_model=MarketplaceConnectionOut)
def run_mercado_livre_item_diagnostics(data: MarketplaceItemDiagnosticsRequest, db: Session = Depends(get_db)):
    service = MercadoLivreDiagnostics(db)
    try:
        try:
            return service.run_item(data.item)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    finally:
        service.close()


@router.get("/radar/mercado-livre/status", response_model=RadarStatusOut)
def mercado_livre_radar_status(db: Session = Depends(get_db)):
    service = MercadoLivreRadar(db)
    try: return service.status()
    finally: service.close()


@router.post("/radar/mercado-livre/categories/sync")
def sync_mercado_livre_radar_categories(db: Session = Depends(get_db)):
    service = MercadoLivreRadar(db)
    try:
        try: return service.sync_categories()
        except RadarDomainError as exc: raise HTTPException(409, str(exc)) from exc
    finally: service.close()


@router.get("/radar/mercado-livre/categories", response_model=list[MarketplaceCategoryOut])
def mercado_livre_radar_categories(db: Session = Depends(get_db)):
    return db.scalars(select(MarketplaceCategory).where(MarketplaceCategory.provider == "MERCADO_LIVRE").order_by(MarketplaceCategory.name)).all()


@router.post("/radar/mercado-livre/runs", response_model=RadarRunOut, status_code=201)
def create_mercado_livre_radar_run(data: RadarRunCreate, db: Session = Depends(get_db)):
    service = MercadoLivreRadar(db)
    try:
        try: return service.run(data.categoryId)
        except RadarDomainError as exc: raise HTTPException(409, str(exc)) from exc
    finally: service.close()


@router.get("/radar/mercado-livre/runs", response_model=list[RadarRunOut])
def mercado_livre_radar_runs(limit: int = Query(default=50, ge=1, le=50), db: Session = Depends(get_db)):
    return db.scalars(select(RadarRun).where(RadarRun.provider == "MERCADO_LIVRE").order_by(RadarRun.started_at.desc()).limit(limit)).all()


@router.get("/radar/mercado-livre/runs/{run_id}", response_model=RadarRunOut)
def mercado_livre_radar_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(RadarRun, run_id)
    if not run: raise HTTPException(404, "Execução do Radar não encontrada")
    return run


@router.get("/radar/mercado-livre/runs/{run_id}/signals", response_model=list[RadarSignalOut])
def mercado_livre_radar_signals(run_id: str, db: Session = Depends(get_db)):
    if not db.get(RadarRun, run_id): raise HTTPException(404, "Execução do Radar não encontrada")
    return db.scalars(select(RadarSignal).where(RadarSignal.radar_run_id == run_id).order_by(RadarSignal.source_type, RadarSignal.rank)).all()

def candidate_or_404(db,id):
    row=db.get(CuratorCandidate,id)
    if not row: raise HTTPException(404,"Candidato não encontrado")
    return row
@router.post("/curator/candidates",response_model=CandidateOut,status_code=201)
def create_candidate(data:CandidateCreate,db:Session=Depends(get_db)):
    values=data.model_dump(); url=values.pop("sourceUrl"); external=values.pop("externalId") or (parse_mlb(url) if values["provider"]=="MERCADO_LIVRE" else None)
    c=CuratorCandidate(provider=values["provider"],site_id="MLB" if values["provider"]=="MERCADO_LIVRE" else None,source_type="MANUAL",entity_type=values["entityType"],external_id=external,category_external_id=values["categoryExternalId"],working_title=values["workingTitle"],source_url=url,notes=values["notes"]);db.add(c);db.flush();log_decision(db,"OPERATOR","CURATOR_CANDIDATE","CURATOR_CANDIDATE_CREATED",c.id,metadata={"candidateId":c.id});db.commit();db.refresh(c);return c
@router.get("/curator/candidates",response_model=list[CandidateOut])
def candidates(status:str|None=None,evidence_status:str|None=None,evidence_level:str|None=None,provider:str|None=None,db:Session=Depends(get_db)):
    q=select(CuratorCandidate)
    for col,val in [(CuratorCandidate.status,status),(CuratorCandidate.evidence_status,evidence_status),(CuratorCandidate.evidence_level,evidence_level),(CuratorCandidate.provider,provider)]:
        if val:q=q.where(col==val)
    return db.scalars(q.order_by(CuratorCandidate.updated_at.desc())).all()
@router.post("/curator/candidates/from-radar/{signal_id}",response_model=CandidateOut)
def candidate_from_radar(signal_id:str,db:Session=Depends(get_db)):
    signal=db.get(RadarSignal,signal_id)
    if not signal:raise HTTPException(404,"Sinal do Radar não encontrado")
    c,_=from_radar(db,signal);db.commit();db.refresh(c);return c
@router.get("/curator/candidates/{id}",response_model=CandidateOut)
def get_candidate(id:str,db:Session=Depends(get_db)):return candidate_or_404(db,id)
@router.patch("/curator/candidates/{id}",response_model=CandidateOut)
def update_candidate(id:str,data:CandidatePatch,db:Session=Depends(get_db)):
    c=candidate_or_404(db,id); allowed={"NEW":{"INVESTIGATING","ARCHIVED"},"INVESTIGATING":{"READY_FOR_REVIEW","ARCHIVED"},"READY_FOR_REVIEW":{"INVESTIGATING","ARCHIVED"},"ARCHIVED":{"INVESTIGATING"}}
    values=data.model_dump(exclude_unset=True); new=values.pop("status",None)
    if new and new!=c.status and new not in allowed[c.status]:raise HTTPException(409,"Transição de status inválida")
    for key,val in values.items():setattr(c,{"workingTitle":"working_title","sourceUrl":"source_url","notes":"notes"}[key],val)
    if new:c.status=new
    log_decision(db,"OPERATOR","CURATOR_CANDIDATE","CURATOR_CANDIDATE_UPDATED",c.id,metadata={"candidateId":c.id,"status":c.status});db.commit();db.refresh(c);return c
@router.post("/curator/candidates/{id}/archive",response_model=CandidateOut)
def archive_candidate(id:str,db:Session=Depends(get_db)):
    c=candidate_or_404(db,id);c.status="ARCHIVED";log_decision(db,"OPERATOR","CURATOR_CANDIDATE","CURATOR_CANDIDATE_ARCHIVED",c.id,metadata={"candidateId":c.id});db.commit();db.refresh(c);return c
@router.post("/curator/candidates/{id}/reopen",response_model=CandidateOut)
def reopen_candidate(id:str,db:Session=Depends(get_db)):
    c=candidate_or_404(db,id);c.status="INVESTIGATING";log_decision(db,"OPERATOR","CURATOR_CANDIDATE","CURATOR_CANDIDATE_REOPENED",c.id,metadata={"candidateId":c.id});db.commit();db.refresh(c);return c
@router.post("/curator/candidates/{id}/evidence",response_model=EvidenceOut,status_code=201)
def add_evidence(id:str,data:EvidenceCreate,db:Session=Depends(get_db)):
    c=candidate_or_404(db,id)
    if data.evidenceType not in EVIDENCE_TYPES:raise HTTPException(422,"Tipo de evidência inválido")
    values={k.replace("evidenceType","evidence_type").replace("valueText","value_text").replace("valueNumber","value_number").replace("valueCents","value_cents").replace("valueJson","value_json").replace("sourceKind","source_kind").replace("sourceName","source_name").replace("sourceUrl","source_url").replace("sourceReference","source_reference").replace("verificationStatus","verification_status").replace("observedAt","observed_at").replace("validUntil","valid_until").replace("metadata","metadata_"):v for k,v in data.model_dump(exclude_none=True).items()};e=CuratorEvidence(candidate_id=id,**values);db.add(e);db.flush();refresh(db,c);log_decision(db,"OPERATOR","CURATOR_EVIDENCE","CURATOR_EVIDENCE_ADDED",e.id,metadata={"candidateId":id,"evidenceType":e.evidence_type,"sourceKind":e.source_kind});db.commit();db.refresh(e);return EvidenceOut.model_validate(e).model_copy(update={"isStale":stale(e)})
@router.get("/curator/candidates/{id}/evidence",response_model=list[EvidenceOut])
def evidence(id:str,db:Session=Depends(get_db)):
    candidate_or_404(db,id);return [EvidenceOut.model_validate(e).model_copy(update={"isStale":stale(e)}) for e in db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==id).order_by(CuratorEvidence.observed_at.desc()))]
@router.get("/curator/candidates/{id}/checklist")
def candidate_checklist(id:str,db:Session=Depends(get_db)):
    c=candidate_or_404(db,id); ev=refresh(db,c);db.commit();return {"evidenceStatus":c.evidence_status,"evidenceLevel":c.evidence_level,"items":checklist(c,ev)}
@router.patch("/curator/evidence/{id}",response_model=EvidenceOut)
def patch_evidence(id:str,data:EvidencePatch,db:Session=Depends(get_db)):
    e=db.get(CuratorEvidence,id)
    if not e:raise HTTPException(404,"Evidência não encontrada")
    mapping={"evidenceType":"evidence_type","valueText":"value_text","valueNumber":"value_number","valueCents":"value_cents","valueJson":"value_json","sourceKind":"source_kind","sourceName":"source_name","sourceUrl":"source_url","sourceReference":"source_reference","verificationStatus":"verification_status","observedAt":"observed_at","validUntil":"valid_until","metadata":"metadata_"}
    for key,value in data.model_dump(exclude_unset=True).items():setattr(e,mapping.get(key,key),value)
    if e.evidence_type not in EVIDENCE_TYPES:raise HTTPException(422,"Tipo de evidência inválido")
    refresh(db,candidate_or_404(db,e.candidate_id));log_decision(db,"OPERATOR","CURATOR_EVIDENCE","CURATOR_EVIDENCE_UPDATED",e.id,metadata={"candidateId":e.candidate_id,"evidenceType":e.evidence_type,"sourceKind":e.source_kind});db.commit();db.refresh(e);return EvidenceOut.model_validate(e).model_copy(update={"isStale":stale(e)})
@router.delete("/curator/evidence/{id}",status_code=204)
def delete_evidence(id:str,db:Session=Depends(get_db)):
    e=db.get(CuratorEvidence,id)
    if not e:raise HTTPException(404,"Evidência não encontrada")
    cid=e.candidate_id;db.delete(e);db.flush();refresh(db,candidate_or_404(db,cid));log_decision(db,"OPERATOR","CURATOR_EVIDENCE","CURATOR_EVIDENCE_REMOVED",id,metadata={"candidateId":cid});db.commit()
@router.post("/curator/candidates/{id}/assess",response_model=AssessmentOut,status_code=201)
def assess_candidate(id:str,db:Session=Depends(get_db)):
    c=candidate_or_404(db,id);refresh(db,c);return CuratorAssessmentService(db).assess(c)
@router.get("/curator/candidates/{id}/assessments",response_model=list[AssessmentOut])
def assessments(id:str,db:Session=Depends(get_db)):
    candidate_or_404(db,id);return db.scalars(select(CuratorAssessment).where(CuratorAssessment.candidate_id==id).order_by(CuratorAssessment.assessment_version.desc())).all()
@router.get("/curator/candidates/{id}/assessments/latest",response_model=AssessmentOut|None)
def latest_assessment(id:str,db:Session=Depends(get_db)):
    candidate_or_404(db,id);return db.scalar(select(CuratorAssessment).where(CuratorAssessment.candidate_id==id).order_by(CuratorAssessment.assessment_version.desc()))
@router.get("/curator/assessments/{id}",response_model=AssessmentOut)
def assessment(id:str,db:Session=Depends(get_db)):
    row=db.get(CuratorAssessment,id)
    if not row:raise HTTPException(404,"Avaliação não encontrada")
    return row

@router.post("/campaigns",response_model=CampaignOut,status_code=201)
def create_campaign(data:CampaignCreate,db:Session=Depends(get_db)):return create_from_assessment(db,data.assessmentId,data.name)
@router.post("/campaigns/from-assessment/{assessment_id}",response_model=CampaignOut,status_code=201)
def campaign_from_assessment(assessment_id:str,data:CampaignCreate,db:Session=Depends(get_db)):return create_from_assessment(db,assessment_id,data.name)
@router.get("/campaigns",response_model=list[CampaignOut])
def campaigns(status:str|None=None,priority:str|None=None,verdict:str|None=None,channel:str|None=None,db:Session=Depends(get_db)):
    q=select(Campaign)
    if status:q=q.where(Campaign.status==status)
    if priority:q=q.where(Campaign.campaign_priority==priority)
    if verdict:q=q.where(Campaign.editorial_verdict_snapshot==verdict)
    if channel:q=q.join(CampaignChannel).where(CampaignChannel.channel==channel,CampaignChannel.enabled==True)
    return db.scalars(q.order_by(Campaign.updated_at.desc())).unique().all()
@router.get("/campaigns/{id}",response_model=CampaignOut)
def get_campaign(id:str,db:Session=Depends(get_db)):return campaign_or_404(db,id)
@router.patch("/campaigns/{id}",response_model=CampaignOut)
def patch_campaign(id:str,data:CampaignPatch,db:Session=Depends(get_db)):
    row=campaign_or_404(db,id);editable(row);mapping={"targetAudience":"target_audience","editorialPositioning":"editorial_positioning","primaryMessage":"primary_message","affiliateUrl":"affiliate_url","disclosureText":"disclosure_text","ctaStrategy":"cta_strategy","requiresFinancialSpend":"requires_financial_spend"};values=data.model_dump(exclude_unset=True);verified=values.pop("affiliateUrlVerified",None)
    for key,value in values.items():setattr(row,mapping.get(key,key),validate_url(value) if key=="affiliateUrl" else value)
    if verified is not None:row.affiliate_url_verified_at=utcnow() if verified and row.affiliate_url else None
    log_decision(db,"OPERATOR","CAMPAIGN","CAMPAIGN_UPDATED",row.id,metadata={"affiliateUrlPresent":bool(row.affiliate_url)});db.commit();db.refresh(row);return row
def child(db,model,id,campaign_id):
    row=db.get(model,id)
    if not row or row.campaign_id!=campaign_id:raise HTTPException(404,"Item da campanha não encontrado")
    editable(campaign_or_404(db,campaign_id));return row
@router.post("/campaigns/{id}/channels",response_model=ChannelOut,status_code=201)
def add_channel(id:str,data:ChannelData,db:Session=Depends(get_db)):
    editable(campaign_or_404(db,id));row=CampaignChannel(campaign_id=id,channel=data.channel,enabled=data.enabled,publication_mode=data.publicationMode,platform_notes=data.platformNotes);db.add(row);db.flush();log_decision(db,"OPERATOR","CAMPAIGN","CAMPAIGN_CHANNEL_ADDED",id,metadata={"channel":data.channel});db.commit();db.refresh(row);return row
@router.patch("/campaigns/{id}/channels/{child_id}",response_model=ChannelOut)
def patch_channel(id:str,child_id:str,data:ChannelPatch,db:Session=Depends(get_db)):
    row=child(db,CampaignChannel,child_id,id);mapping={"publicationMode":"publication_mode","platformNotes":"platform_notes"}
    for k,v in data.model_dump(exclude_unset=True).items():setattr(row,mapping.get(k,k),v)
    db.commit();db.refresh(row);return row
@router.post("/campaigns/{id}/angles",response_model=AngleOut,status_code=201)
def add_angle(id:str,data:AngleData,db:Session=Depends(get_db)):
    editable(campaign_or_404(db,id));row=CampaignAngle(campaign_id=id,angle_type=data.angleType,title=data.title,premise=data.premise,target_segment=data.targetSegment,priority=data.priority,status=data.status);db.add(row);db.flush();log_decision(db,"OPERATOR","CAMPAIGN","CAMPAIGN_ANGLE_ADDED",id,metadata={"angleType":data.angleType});db.commit();db.refresh(row);return row
@router.patch("/campaigns/{id}/angles/{child_id}",response_model=AngleOut)
def patch_angle(id:str,child_id:str,data:AnglePatch,db:Session=Depends(get_db)):
    row=child(db,CampaignAngle,child_id,id);mapping={"targetSegment":"target_segment"}
    for k,v in data.model_dump(exclude_unset=True).items():setattr(row,mapping.get(k,k),v)
    db.commit();db.refresh(row);return row
@router.post("/campaigns/{id}/experiments",response_model=ExperimentOut,status_code=201)
def add_experiment(id:str,data:ExperimentData,db:Session=Depends(get_db)):
    editable(campaign_or_404(db,id));count=db.scalar(select(func.count()).select_from(CampaignExperiment).where(CampaignExperiment.campaign_id==id)) or 0
    if count>=12:raise HTTPException(409,"Limite de 12 experimentos por campanha atingido")
    if data.angleId and not db.scalar(select(CampaignAngle).where(CampaignAngle.id==data.angleId,CampaignAngle.campaign_id==id)):raise HTTPException(422,"Ângulo não pertence à campanha")
    row=CampaignExperiment(campaign_id=id,angle_id=data.angleId,hypothesis=data.hypothesis,status=data.status,hook_strategy=data.hookStrategy,cta_strategy=data.ctaStrategy,target_channel=data.targetChannel,variant_group=data.variantGroup,parent_experiment_id=data.parentExperimentId);db.add(row);db.flush();log_decision(db,"OPERATOR","CAMPAIGN","CAMPAIGN_EXPERIMENT_ADDED",id);db.commit();db.refresh(row);return row
@router.patch("/campaigns/{id}/experiments/{child_id}",response_model=ExperimentOut)
def patch_experiment(id:str,child_id:str,data:ExperimentPatch,db:Session=Depends(get_db)):
    row=child(db,CampaignExperiment,child_id,id);mapping={"hookStrategy":"hook_strategy","ctaStrategy":"cta_strategy","targetChannel":"target_channel","variantGroup":"variant_group"}
    for k,v in data.model_dump(exclude_unset=True).items():setattr(row,mapping.get(k,k),v)
    db.commit();db.refresh(row);return row
@router.get("/campaigns/{id}/channels",response_model=list[ChannelOut])
def campaign_channels(id:str,db:Session=Depends(get_db)):campaign_or_404(db,id);return db.scalars(select(CampaignChannel).where(CampaignChannel.campaign_id==id)).all()
@router.get("/campaigns/{id}/angles",response_model=list[AngleOut])
def campaign_angles(id:str,db:Session=Depends(get_db)):campaign_or_404(db,id);return db.scalars(select(CampaignAngle).where(CampaignAngle.campaign_id==id).order_by(CampaignAngle.priority.desc())).all()
@router.get("/campaigns/{id}/experiments",response_model=list[ExperimentOut])
def campaign_experiments(id:str,db:Session=Depends(get_db)):campaign_or_404(db,id);return db.scalars(select(CampaignExperiment).where(CampaignExperiment.campaign_id==id)).all()
@router.get("/campaigns/{id}/readiness")
def campaign_readiness(id:str,db:Session=Depends(get_db)):return readiness(db,campaign_or_404(db,id))
@router.post("/campaigns/{id}/submit-for-approval",response_model=ApprovalOut)
def submit_campaign(id:str,db:Session=Depends(get_db)):return submit(db,campaign_or_404(db,id))
@router.post("/campaigns/{id}/pause",response_model=CampaignOut)
def pause_campaign(id:str,db:Session=Depends(get_db)):
    row=campaign_or_404(db,id)
    if row.status!="APPROVED":raise HTTPException(409,"Somente campanhas aprovadas podem ser pausadas")
    row.status="PAUSED";log_decision(db,"OPERATOR","CAMPAIGN","CAMPAIGN_PAUSED",id);db.commit();db.refresh(row);return row
@router.post("/campaigns/{id}/archive",response_model=CampaignOut)
def archive_campaign(id:str,db:Session=Depends(get_db)):
    row=campaign_or_404(db,id)
    if row.status=="ARCHIVED":raise HTTPException(409,"Campanha já está arquivada")
    row.status="ARCHIVED";log_decision(db,"OPERATOR","CAMPAIGN","CAMPAIGN_ARCHIVED",id);db.commit();db.refresh(row);return row

@router.post("/creatives/from-campaign/{campaign_id}",response_model=CreativeOut,status_code=201)
def create_creative(campaign_id:str,data:CreativeCreate,db:Session=Depends(get_db)):return creative_service.create(db,campaign_or_404(db,campaign_id),data)
@router.post("/creatives/from-experiment/{experiment_id}",response_model=CreativeOut,status_code=201)
def create_creative_experiment(experiment_id:str,data:CreativeCreate,db:Session=Depends(get_db)):
    experiment=db.get(CampaignExperiment,experiment_id)
    if not experiment:raise HTTPException(404,"Experimento não encontrado")
    return creative_service.create(db,campaign_or_404(db,experiment.campaign_id),data,experiment)
@router.get("/creatives",response_model=list[CreativeOut])
def creatives(status:str|None=None,campaign_id:str|None=None,channel:str|None=None,content_type:str|None=None,db:Session=Depends(get_db)):
    q=select(Creative)
    for col,val in [(Creative.status,status),(Creative.campaign_id,campaign_id),(Creative.target_channel,channel),(Creative.content_type,content_type)]:
        if val:q=q.where(col==val)
    return db.scalars(q.order_by(Creative.updated_at.desc())).all()
@router.get("/creatives/{id}",response_model=CreativeOut)
def get_creative(id:str,db:Session=Depends(get_db)):return creative_service.creative_or_404(db,id)
@router.patch("/creatives/{id}",response_model=CreativeOut)
def patch_creative(id:str,data:CreativePatch,db:Session=Depends(get_db)):
    row=creative_service.creative_or_404(db,id);creative_service.editable(row);mapping={"contentType":"content_type","targetChannel":"target_channel","contentPremise":"content_premise","bodyScript":"body_script","estimatedDurationSeconds":"estimated_duration_seconds","disclosureText":"disclosure_text","variantLabel":"variant_label"}
    for key,value in data.model_dump(exclude_unset=True).items():setattr(row,mapping.get(key,key),value)
    log_decision(db,"OPERATOR","CREATIVE","CREATIVE_UPDATED",id,metadata={"fields":list(data.model_dump(exclude_unset=True))});db.commit();db.refresh(row);return row
@router.get("/creatives/{id}/scenes",response_model=list[SceneOut])
def creative_scenes(id:str,db:Session=Depends(get_db)):creative_service.creative_or_404(db,id);return db.scalars(select(CreativeScene).where(CreativeScene.creative_id==id).order_by(CreativeScene.order_index)).all()
@router.post("/creatives/{id}/scenes",response_model=SceneOut,status_code=201)
def add_scene(id:str,data:SceneData,db:Session=Depends(get_db)):
    row=creative_service.creative_or_404(db,id);creative_service.editable(row);v=data.model_dump();scene=CreativeScene(creative_id=id,order_index=v.pop("orderIndex"),scene_type=v.pop("sceneType"),narration_text=v.pop("narrationText"),on_screen_text=v.pop("onScreenText"),visual_instruction=v.pop("visualInstruction"),avatar_state=v.pop("avatarState"),duration_seconds=v.pop("durationSeconds"),required_warning_codes=v.pop("requiredWarningCodes"),**v);db.add(scene);db.flush();log_decision(db,"OPERATOR","CREATIVE","CREATIVE_SCENE_ADDED",id,metadata={"sceneId":scene.id});db.commit();db.refresh(scene);return scene
@router.patch("/creatives/{id}/scenes/{scene_id}",response_model=SceneOut)
def patch_scene(id:str,scene_id:str,data:ScenePatch,db:Session=Depends(get_db)):
    creative_service.editable(creative_service.creative_or_404(db,id));scene=db.get(CreativeScene,scene_id)
    if not scene or scene.creative_id!=id:raise HTTPException(404,"Cena não encontrada")
    mapping={"orderIndex":"order_index","sceneType":"scene_type","narrationText":"narration_text","onScreenText":"on_screen_text","visualInstruction":"visual_instruction","avatarState":"avatar_state","durationSeconds":"duration_seconds","requiredWarningCodes":"required_warning_codes"}
    for key,value in data.model_dump(exclude_unset=True).items():setattr(scene,mapping.get(key,key),value)
    log_decision(db,"OPERATOR","CREATIVE","CREATIVE_SCENE_UPDATED",id,metadata={"sceneId":scene.id});db.commit();db.refresh(scene);return scene
@router.delete("/creatives/{id}/scenes/{scene_id}",status_code=204)
def delete_scene(id:str,scene_id:str,db:Session=Depends(get_db)):
    creative_service.editable(creative_service.creative_or_404(db,id));scene=db.get(CreativeScene,scene_id)
    if not scene or scene.creative_id!=id:raise HTTPException(404,"Cena não encontrada")
    db.delete(scene);log_decision(db,"OPERATOR","CREATIVE","CREATIVE_SCENE_REMOVED",id,metadata={"sceneId":scene_id});db.commit()
@router.post("/creatives/{id}/generate-template",response_model=CreativeOut)
def generate_creative_template(id:str,data:TemplateGenerate=TemplateGenerate(),db:Session=Depends(get_db)):return creative_service.generate_template(db,creative_service.creative_or_404(db,id),data.overwrite)
@router.get("/creatives/{id}/compliance")
def creative_compliance(id:str,db:Session=Depends(get_db)):return creative_service.compliance(db,creative_service.creative_or_404(db,id))
@router.get("/creatives/{id}/readiness")
def creative_readiness(id:str,db:Session=Depends(get_db)):return creative_service.readiness(db,creative_service.creative_or_404(db,id))
@router.post("/creatives/{id}/submit-for-review",response_model=ApprovalOut)
def submit_creative(id:str,db:Session=Depends(get_db)):return creative_service.submit(db,creative_service.creative_or_404(db,id))
@router.post("/creatives/{id}/variant",response_model=CreativeOut,status_code=201)
def creative_variant(id:str,data:dict|None=None,db:Session=Depends(get_db)):return creative_service.variant(db,creative_service.creative_or_404(db,id),(data or {}).get("variantLabel"))
@router.post("/creatives/{id}/archive",response_model=CreativeOut)
def archive_creative(id:str,db:Session=Depends(get_db)):
    row=creative_service.creative_or_404(db,id);row.status="ARCHIVED";log_decision(db,"OPERATOR","CREATIVE","CREATIVE_ARCHIVED",id);db.commit();db.refresh(row);return row
