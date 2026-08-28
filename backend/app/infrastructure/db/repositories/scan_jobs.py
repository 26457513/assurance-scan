"""Repository for `scan_jobs`."""
from __future__ import annotations

import datetime as dt
from typing import Sequence

from sqlalchemy import select, update

from app.infrastructure.db.models import ScanJob
from app.infrastructure.db.repositories.base import BaseRepository


class ScanJobRepository(BaseRepository[ScanJob]):
    """Atomic operations on `scan_jobs`."""

    model = ScanJob

    async def create(self, run_id: str) -> ScanJob:
        job = ScanJob(
            run_id=run_id,
            state="queued",
            queued_at=dt.datetime.now(dt.timezone.utc),
        )
        self.session.add(job)
        await self._flush()
        return job

    async def mark_running(self, run_id: str) -> None:
        await self.session.execute(
            update(ScanJob)
            .where(ScanJob.run_id == run_id)
            .values(state="running", started_at=dt.datetime.now(dt.timezone.utc))
        )

    async def mark_completed(self, run_id: str) -> None:
        await self.session.execute(
            update(ScanJob)
            .where(ScanJob.run_id == run_id)
            .values(state="completed", completed_at=dt.datetime.now(dt.timezone.utc))
        )

    async def mark_failed(self, run_id: str, error_message: str) -> None:
        await self.session.execute(
            update(ScanJob)
            .where(ScanJob.run_id == run_id)
            .values(
                state="failed",
                completed_at=dt.datetime.now(dt.timezone.utc),
                error_message=error_message,
            )
        )

    async def mark_cancelled(self, run_id: str) -> None:
        await self.session.execute(
            update(ScanJob)
            .where(ScanJob.run_id == run_id)
            .values(
                state="cancelled",
                completed_at=dt.datetime.now(dt.timezone.utc),
            )
        )

    async def get(self, run_id: str) -> ScanJob | None:
        return await self.session.get(ScanJob, run_id)

    async def list_recent(self, limit: int = 50) -> Sequence[ScanJob]:
        result = await self.session.execute(
            select(ScanJob).order_by(ScanJob.queued_at.desc()).limit(limit)
        )
        return result.scalars().all()
