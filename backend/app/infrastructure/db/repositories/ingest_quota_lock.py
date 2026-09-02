"""Shared transaction lock for all local and GitHub quota reservations."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import IngestQuotaLock


QUOTA_LOCK_SESSION_KEY = "ingest_quota_lock"


async def acquire_global_ingest_quota_lock(session: AsyncSession) -> None:
    """Acquire the one cross-origin lock and mark its caller-owned transaction."""
    if session.in_transaction():
        raise RuntimeError("quota reservation requires a clean session")
    if session.get_bind().dialect.name != "sqlite":
        raise RuntimeError("ingest quota locking requires the supported SQLite database")
    await session.execute(text("BEGIN IMMEDIATE"))
    locked = await session.get(IngestQuotaLock, "global")
    if locked is None:
        session.add(IngestQuotaLock(lock_name="global"))
        await session.flush()
    session.info[QUOTA_LOCK_SESSION_KEY] = True


__all__ = ["QUOTA_LOCK_SESSION_KEY", "acquire_global_ingest_quota_lock"]
