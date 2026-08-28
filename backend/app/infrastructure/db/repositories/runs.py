"""Repository for the `runs` table."""
from __future__ import annotations

import datetime as dt
from typing import Sequence

from sqlalchemy import select, update

from app.infrastructure.db.models import Run
from app.infrastructure.db.repositories.base import BaseRepository


class RunRepository(BaseRepository[Run]):
    """Atomic operations on `runs`."""

    model = Run

    async def create(
        self,
        run_id: str,
        project_id: int,
        origin: str,
        options_json: str = "{}",
    ) -> Run:
        run = Run(
            run_id=run_id,
            project_id=project_id,
            origin=origin,
            options_json=options_json,
            status="queued",
        )
        self.session.add(run)
        await self._flush()
        return run

    async def mark_running(self, run_id: str) -> None:
        await self.session.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(status="running", started_at=dt.datetime.now(dt.timezone.utc))
        )

    async def mark_completed(self, run_id: str, findings_json: str) -> None:
        await self.session.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(
                status="completed",
                completed_at=dt.datetime.now(dt.timezone.utc),
                findings_json=findings_json,
            )
        )

    async def mark_failed(self, run_id: str, error_message: str) -> None:
        await self.session.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(
                status="failed",
                completed_at=dt.datetime.now(dt.timezone.utc),
                error_message=error_message,
            )
        )

    async def get(self, run_id: str) -> Run | None:
        return await self.session.get(Run, run_id)

    async def list_recent(
        self,
        limit: int = 50,
        project_id: int | None = None,
        origin: str | None = None,
    ) -> Sequence[Run]:
        statement = select(Run)
        if project_id is not None:
            statement = statement.where(Run.project_id == project_id)
        if origin is not None:
            statement = statement.where(Run.origin == origin)
        result = await self.session.execute(
            statement.order_by(Run.started_at.desc(), Run.run_id.desc()).limit(limit)
        )
        return result.scalars().all()
