from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from apps.api.app.db.session import get_db
from apps.api.app.db.models import AppSettings, Approval, Notification, AgentTask, DecisionLog, MarketplaceCapability
from apps.api.app.integrations.mercado_livre import MercadoLivreDiagnostics
from apps.api.app.schemas import *
from apps.api.app.services.operations import *
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
