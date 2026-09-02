"""SQLAlchemy persistence for minimized ingest-attempt evidence."""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import IngestAttempt
from app.modules.atomic.ingestion.ingest_attempt import IngestAttemptRecord


class SqlAlchemyIngestAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def stage(self, record: IngestAttemptRecord) -> None:
        self.session.add(IngestAttempt(**record.__dict__))
        await self.session.flush()

    async def record(self, record: IngestAttemptRecord) -> None:
        await self.stage(record)
        await self.session.commit()

    async def purge_expired(self, *, now: dt.datetime) -> int:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                delete(IngestAttempt)
                .where(IngestAttempt.expires_at <= now)
                .execution_options(synchronize_session=False)
            ),
        )
        await self.session.commit()
        return int(result.rowcount or 0)


__all__ = ["SqlAlchemyIngestAttemptRepository"]
