"""Repository for the `scanner_runs` table."""
from __future__ import annotations

import datetime as dt
from typing import Sequence

from sqlalchemy import select, update

from app.infrastructure.db.models import ScannerRun
from app.infrastructure.db.repositories.base import BaseRepository


class ScannerRunRepository(BaseRepository[ScannerRun]):
    """Atomic operations on `scanner_runs`."""

    model = ScannerRun

    async def create(self, run_id: str, scanner_kind: str) -> ScannerRun:
        scanner_run = ScannerRun(
            run_id=run_id,
            scanner_kind=scanner_kind,
            status="pending",
        )
        self.session.add(scanner_run)
        await self._flush()
        return scanner_run

    async def mark_running(self, scanner_run_id: int) -> None:
        await self.session.execute(
            update(ScannerRun)
            .where(ScannerRun.id == scanner_run_id)
            .values(status="running", started_at=dt.datetime.now(dt.timezone.utc))
        )

    async def mark_completed(self, scanner_run_id: int) -> None:
        await self.session.execute(
            update(ScannerRun)
            .where(ScannerRun.id == scanner_run_id)
            .values(
                status="completed",
                completed_at=dt.datetime.now(dt.timezone.utc),
            )
        )

    async def mark_failed(self, scanner_run_id: int, error_message: str) -> None:
        await self.session.execute(
            update(ScannerRun)
            .where(ScannerRun.id == scanner_run_id)
            .values(
                status="failed",
                completed_at=dt.datetime.now(dt.timezone.utc),
                error_message=error_message,
            )
        )

    async def list_for_run(self, run_id: str) -> Sequence[ScannerRun]:
        result = await self.session.execute(
            select(ScannerRun)
            .where(ScannerRun.run_id == run_id)
            .order_by(ScannerRun.scanner_kind)
        )
        return result.scalars().all()
