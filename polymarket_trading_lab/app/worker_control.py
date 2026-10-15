"""In-process lifecycle controls for the local paper worker."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import SystemHealth
from .config import get_settings
from .worker import PaperMarketWorker
from .worker_lock import WorkerLock


class WorkerController:
    """Start and stop one paper worker task in the current API process."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._worker: PaperMarketWorker | None = None

    def _task_state(self) -> str:
        if self._task is None:
            return "stopped"
        if self._task.done():
            if self._task.cancelled():
                return "stopped"
            return "error" if self._task.exception() else "stopped"
        return "running"

    def status(self, session: Session) -> dict[str, object]:
        health = session.scalar(select(SystemHealth).where(SystemHealth.component == "worker"))
        state = self._task_state()
        if health is not None and state == "stopped" and health.status == "running":
            state = "stale"
        return {
            "component": "worker",
            "status": state,
            "paper_only": True,
            "real_execution": False,
            "queue_model": get_settings().paper_queue_model,
            "checked_at": health.checked_at.astimezone(timezone.utc).isoformat() if health else None,
            "details": health.details if health else "worker has not been started",
        }

    @staticmethod
    def _write_health(session: Session, status: str, details: str) -> None:
        row = session.scalar(select(SystemHealth).where(SystemHealth.component == "worker"))
        now = datetime.now(timezone.utc)
        if row is None:
            session.add(SystemHealth(component="worker", status=status, checked_at=now, details=details))
        else:
            row.status = status
            row.checked_at = now
            row.details = details
        session.commit()

    async def start(self, session_factory, worker: PaperMarketWorker | None = None) -> dict[str, object]:
        state = self._task_state()
        if state == "running":
            with session_factory() as session:
                return self.status(session)
        if worker is None:
            probe = WorkerLock(get_settings().database_url)
            probe.acquire()  # raises WorkerAlreadyRunning if another process owns the worker
            probe.release()
        self._worker = worker or PaperMarketWorker(session_factory=session_factory)
        with session_factory() as health_session:
            self._write_health(health_session, "running", "paper worker started by local API")

        async def run() -> None:
            try:
                await self._worker.run_forever()
            finally:
                with session_factory() as health_session:
                    self._write_health(health_session, "stopped", "paper worker stopped")

        self._task = asyncio.create_task(run(), name="polymarket-paper-worker")
        with session_factory() as status_session:
            return self.status(status_session)

    async def stop(self, session_factory) -> dict[str, object]:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        with session_factory() as health_session:
            self._write_health(health_session, "stopped", "paper worker stopped by local API")
            return self.status(health_session)


worker_controller = WorkerController()
