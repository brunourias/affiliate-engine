from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.db.models import AppSettings, Approval, Notification, AgentTask, DecisionLog
def utcnow(): return datetime.now(timezone.utc)
def log_decision(db, actor, entity_type, action, entity_id=None, reason=None, metadata=None, is_demo=False):
    db.add(DecisionLog(actor=actor,entity_type=entity_type,entity_id=entity_id,action=action,reason=reason,metadata_=metadata,is_demo=is_demo))
def notify(db,severity,title,message,type="SYSTEM",metadata=None,is_demo=False): db.add(Notification(type=type,severity=severity,title=title,message=message,metadata_=metadata,is_demo=is_demo))
def settings_row(db):
    row=db.get(AppSettings,1)
    if not row: row=AppSettings(id=1); db.add(row); db.flush()
    return row
def decide(db:Session,item:Approval,status:str,reason=None):
    if item.status!="PENDING": raise HTTPException(409,"Esta aprovação já foi decidida")
    item.status=status; item.decision_reason=reason; item.decided_at=utcnow(); item.updated_at=utcnow(); log_decision(db,"OPERATOR","APPROVAL",f"APPROVAL_{status}",item.id,reason,{"type":item.type}); notify(db,"SUCCESS" if status=="APPROVED" else "WARNING",f"Solicitação {status.lower()}",item.title,"APPROVAL",{"approvalId":item.id}); db.commit(); db.refresh(item); return item
VALID={"PENDING":{"RUNNING","CANCELED"},"RUNNING":{"COMPLETED","FAILED","PAUSED","CANCELED"},"PAUSED":{"RUNNING","CANCELED"},"COMPLETED":set(),"FAILED":set(),"CANCELED":set()}
def transition(db,task,new_status,error=None,result=None):
    if new_status not in VALID[task.status]: raise HTTPException(409,f"Transição inválida: {task.status} → {new_status}")
    now=utcnow(); task.status=new_status; task.updated_at=now
    if new_status=="RUNNING": task.started_at=now
    if new_status in {"COMPLETED","FAILED","CANCELED"}: task.finished_at=now
    task.error=error; task.result=result; log_decision(db,"SYSTEM" if task.is_automatic else "OPERATOR","AGENT_TASK",f"TASK_{new_status}",task.id,error,{"type":task.type}); db.commit(); db.refresh(task); return task
def run_task(db,task):
    config=settings_row(db)
    if task.is_automatic and not config.system_automation_enabled: raise HTTPException(409,"Kill Switch ativo: tarefas automáticas não podem iniciar")
    transition(db,task,"RUNNING")
    if task.type=="CONTROLLED_FAILURE": return transition(db,task,"FAILED","Falha controlada solicitada para teste")
    return transition(db,task,"COMPLETED",result={"message":"Heartbeat local concluído com segurança","completedAt":utcnow().isoformat()})
