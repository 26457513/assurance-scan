"""In-process scan queue.

Single-user, single-server. We don't need a real broker (Redis/SQS) —
just an asyncio queue with one consumer. Limits to one active scan at a
time per server (matches the Phase 0 design decision).

If the queue is asked to do more than one scan at once, additional scans
queue up and run sequentially. The API returns immediately with a
`run_id` regardless.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.infrastructure.db.connection import get_sessionmaker
from app.modules.atomic.platform.docker_port import DockerRunner
from app.worker.orchestrator import ScanOrchestrator


log = logging.getLogger(__name__)


def _new_run_id() -> str:
    """Format: YYYYMMDDTHHMMSSZ_<8-char uuid>"""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = uuid.uuid4().hex[:8]
    return f"{stamp}_{short}"


@dataclass
class _PendingScan:
    run_id: str
    project_id: int
    local_path: str
    options: dict[str, Any] = field(default_factory=dict)


class ScanQueue:
    """In-process queue of pending scans, consumed by one worker task."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._queue: asyncio.Queue[_PendingScan] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._sessionmaker: async_sessionmaker | None = None

    async def start(self) -> None:
        """Start the background consumer task."""
        if self._task is not None:
            return
        self._sessionmaker = get_sessionmaker(self.settings)
        self._task = asyncio.create_task(self._consume(), name="scan-queue")
        log.info("scan queue started")

    async def stop(self) -> None:
        """Graceful shutdown. Pending scans are discarded."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        log.info("scan queue stopped")

    def enqueue(
        self,
        project_id: int,
        local_path: str,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Add a scan to the queue. Returns the assigned run_id immediately."""
        run_id = _new_run_id()
        scan = _PendingScan(
            run_id=run_id,
            project_id=project_id,
            local_path=local_path,
            options=options or {},
        )
        self._queue.put_nowait(scan)
        log.info("scan enqueued run_id=%s project_id=%s", run_id, project_id)
        return run_id

    async def _consume(self) -> None:
        """Worker loop. Runs forever until cancelled."""
        while True:
            scan = await self._queue.get()
            try:
                await self._run_one(scan)
            except Exception:
                log.exception("scan crashed run_id=%s", scan.run_id)
            finally:
                self._queue.task_done()

    async def _run_one(self, scan: _PendingScan) -> None:
        """Create a session, build an orchestrator, run the scan."""
        assert self._sessionmaker is not None
        async with self._sessionmaker() as session:
            runner = DockerRunner(project_path=scan.local_path)
            orchestrator = ScanOrchestrator(session=session, runner=runner)
            await orchestrator.execute(
                run_id=scan.run_id,
                project_id=scan.project_id,
                local_path=scan.local_path,
                options=scan.options,
            )
