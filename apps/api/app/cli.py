import sys
from sqlalchemy import delete
from apps.api.app.db.session import SessionLocal
from apps.api.app.db.models import Approval,Notification,AgentTask,DecisionLog
def seed():
    with SessionLocal() as db:
        db.add_all([Approval(type="FINANCIAL",title="Teste local de orçamento",description="Solicitação demonstrativa; não gera nenhum gasto.",requested_payload={"amountCents":0},is_demo=True),Approval(type="STRATEGIC",title="Validar fluxo de aprovação",description="Registro demo para exercitar a decisão do Operator.",is_demo=True),Notification(type="WELCOME",severity="INFO",title="V1-A pronta para validação",message="Dados demonstrativos estão identificados e podem ser removidos com segurança.",is_demo=True),AgentTask(type="SYSTEM_HEARTBEAT",title="Heartbeat demonstrativo",is_automatic=False,is_demo=True),DecisionLog(actor="SYSTEM",entity_type="SEED",action="DEMO_DATA_CREATED",reason="Seed opt-in executado",is_demo=True)])
        db.commit(); print("Dados demo criados.")
def clear():
    with SessionLocal() as db:
        for model in (Approval,Notification,AgentTask,DecisionLog): db.execute(delete(model).where(model.is_demo==True))
        db.commit(); print("Somente dados demo foram removidos.")
if __name__=="__main__":
    {"seed":seed,"clear-demo":clear}.get(sys.argv[1] if len(sys.argv)>1 else "",lambda:print("Use seed ou clear-demo"))()
