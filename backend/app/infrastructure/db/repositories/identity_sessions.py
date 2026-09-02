"""SQLAlchemy persistence for authenticated browser sessions."""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import BrowserSession
from app.modules.atomic.access.server_session import (
    BrowserSessionRecord,
    digest_session_cookie,
)


class SecureIdentityRandom:
    """Production CSPRNG adapter shared by session and OAuth atomic modules."""

    def random_bytes(self, size: int) -> bytes:
        return secrets.token_bytes(size)


class SqlAlchemyBrowserSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, record: BrowserSessionRecord) -> None:
        self.session.add(
            BrowserSession(
                id=record.session_id,
                session_digest=record.session_digest,
                user_id=record.user_id,
                created_at=record.created_at,
                last_seen_at=record.last_seen_at,
                idle_expires_at=record.idle_expires_at,
                absolute_expires_at=record.absolute_expires_at,
                revoked_at=record.revoked_at,
                rotated_from_id=record.rotated_from_id,
            )
        )
        await self.session.commit()

    async def find_by_cookie(self, cookie_value: str) -> BrowserSessionRecord | None:
        try:
            digest = digest_session_cookie(cookie_value)
        except ValueError:
            return None
        row = (
            await self.session.execute(select(BrowserSession).where(BrowserSession.session_digest == digest))
        ).scalar_one_or_none()
        return _session_record(row) if row is not None else None

    async def revoke(self, session_id: str, *, now: dt.datetime) -> bool:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(BrowserSession)
                .where(BrowserSession.id == session_id, BrowserSession.revoked_at.is_(None))
                .values(revoked_at=now)
            ),
        )
        await self.session.commit()
        return bool(result.rowcount)

    async def touch(self, session_id: str, *, now: dt.datetime, idle_expires_at: dt.datetime) -> bool:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(BrowserSession)
                .where(
                    BrowserSession.id == session_id,
                    BrowserSession.revoked_at.is_(None),
                    BrowserSession.idle_expires_at > now,
                    BrowserSession.absolute_expires_at > now,
                )
                .values(last_seen_at=now, idle_expires_at=idle_expires_at)
            ),
        )
        await self.session.commit()
        return bool(result.rowcount)


def _session_record(row: BrowserSession) -> BrowserSessionRecord:
    return BrowserSessionRecord(
        session_id=row.id,
        user_id=row.user_id,
        session_digest=bytes(row.session_digest),
        created_at=_aware(row.created_at),
        last_seen_at=_aware(row.last_seen_at),
        idle_expires_at=_aware(row.idle_expires_at),
        absolute_expires_at=_aware(row.absolute_expires_at),
        revoked_at=_aware(row.revoked_at) if row.revoked_at is not None else None,
        rotated_from_id=row.rotated_from_id,
    )


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value


__all__ = [
    "SecureIdentityRandom",
    "SqlAlchemyBrowserSessionRepository",
]
