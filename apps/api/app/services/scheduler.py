import asyncio, logging
from sqlalchemy import select
from apps.api.app.core.config import settings
from apps.api.app.db.session import SessionLocal
from apps.api.app.db.models import AgentTask
from .operations import settings_row, run_task
log=logging.getLogger("scheduler")
class Scheduler:
    def __init__(self): self.running=False; self.last_tick=None; self._task=None
    async def loop(self):
        self.running=True; log.info("scheduler_started")
        while self.running:
            await asyncio.sleep(settings.scheduler_interval_seconds); self.tick()
    def tick(self):
        from datetime import datetime,timezone
        self.last_tick=datetime.now(timezone.utc)
        with SessionLocal() as db:
            config=settings_row(db)
            if not config.system_automation_enabled: log.info("scheduler_skipped_kill_switch"); return
            task=db.scalar(select(AgentTask).where(AgentTask.status=="PENDING",AgentTask.is_automatic==True).order_by(AgentTask.created_at).limit(1))
            if task: log.info("scheduler_running_task id=%s",task.id); run_task(db,task)
    def start(self): self._task=asyncio.create_task(self.loop())
    async def stop(self): self.running=False; self._task.cancel() if self._task else None
scheduler=Scheduler()
