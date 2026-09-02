"""Security contract tests for authenticated browser sessions."""

from __future__ import annotations

import datetime as dt
import hashlib

import pytest
from sqlalchemy import select

from app.infrastructure.db.models import BrowserSession, User
from app.infrastructure.db.repositories.identity_sessions import SqlAlchemyBrowserSessionRepository
from app.modules.atomic.access.server_session import (
    SESSION_ABSOLUTE_LIMIT,
    SESSION_IDLE_LIMIT,
    SessionDecision,
    authenticate_browser_session,
    issue_browser_session,
    refreshed_idle_expiry,
)


NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)


class DeterministicRandom:
    def __init__(self) -> None:
        self.counter = 0

    def random_bytes(self, size: int) -> bytes:
        self.counter += 1
        return bytes([self.counter]) * size


def test_browser_session_uses_opaque_digest_and_enforces_both_expiries() -> None:
    issued = issue_browser_session(user_id=7, now=NOW, random=DeterministicRandom())

    assert issued.cookie_value.startswith("ass_v1_")
    assert len(issued.cookie_value.removeprefix("ass_v1_")) == 43
    assert issued.cookie_value.encode() not in issued.record.session_digest
    assert issued.record.session_digest == hashlib.sha256(issued.cookie_value.encode()).digest()
    assert issued.record.idle_expires_at == NOW + SESSION_IDLE_LIMIT
    assert issued.record.absolute_expires_at == NOW + SESSION_ABSOLUTE_LIMIT
    assert (
        authenticate_browser_session(issued.cookie_value, issued.record, now=NOW).decision
        is SessionDecision.AUTHENTICATED
    )
    assert (
        authenticate_browser_session(issued.cookie_value, issued.record, now=issued.record.idle_expires_at).decision
        is SessionDecision.IDLE_EXPIRED
    )
    assert (
        authenticate_browser_session(
            issued.cookie_value,
            issued.record,
            now=issued.record.absolute_expires_at,
        ).decision
        is SessionDecision.ABSOLUTE_EXPIRED
    )


def test_idle_refresh_never_crosses_absolute_limit() -> None:
    issued = issue_browser_session(user_id=7, now=NOW, random=DeterministicRandom())
    near_absolute = issued.record.absolute_expires_at - dt.timedelta(hours=1)
    assert refreshed_idle_expiry(issued.record, now=near_absolute) == issued.record.absolute_expires_at


@pytest.mark.asyncio
async def test_repository_stores_no_plaintext_cookie(session) -> None:
    user = User(email="session-user@example.test", role="user", created_at=NOW)
    session.add(user)
    await session.commit()
    issued_session = issue_browser_session(user_id=user.id, now=NOW, random=DeterministicRandom())
    sessions = SqlAlchemyBrowserSessionRepository(session)
    await sessions.create(issued_session.record)

    stored_session = (await session.execute(select(BrowserSession))).scalar_one()
    assert issued_session.cookie_value.encode() not in bytes(stored_session.session_digest)
    assert (await sessions.find_by_cookie(issued_session.cookie_value)) == issued_session.record
