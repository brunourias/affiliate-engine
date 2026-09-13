import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone

from sqlalchemy import select

from apps.api.app.core.config import settings
from apps.api.app.db.models import AgentTask
from apps.api.app.db.session import SessionLocal
from .operations import run_task, settings_row

log = logging.getLogger('scheduler')


class Scheduler:
    def __init__(self) -> None:
        self.running = False
        self.last_tick: datetime | None = None
        self._task: asyncio.Task[None] | None = None

    async def loop(self) -> None:
        self.running = True
        log.info('scheduler_started')
        try:
            while self.running:
                await asyncio.sleep(settings.scheduler_interval_seconds)
                self.tick()
        except asyncio.CancelledError:
            log.info('scheduler_cancelled')
            raise
        finally:
            self.running = False
            log.info('scheduler_stopped')

    def tick(self) -> None:
        self.last_tick = datetime.now(timezone.utc)
        with SessionLocal() as db:
            config = settings_row(db)
            if not config.system_automation_enabled:
                log.info('scheduler_skipped_kill_switch')
                return
            task = db.scalar(
                select(AgentTask)
                .where(AgentTask.status == 'PENDING', AgentTask.is_automatic.is_(True))
                .order_by(AgentTask.created_at)
                .limit(1)
            )
            if task:
                log.info('scheduler_running_task id=%s', task.id)
                run_task(db, task)

    def start(self) -> asyncio.Task[None]:
        if self._task is not None and not self._task.done():
            log.debug('scheduler_start_ignored_already_running')
            return self._task
        self._task = asyncio.create_task(self.loop(), name='affiliate-engine-scheduler')
        return self._task

    async def stop(self) -> None:
        self.running = False
        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._task = None


scheduler = Scheduler()
