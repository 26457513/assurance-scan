"""SQLAlchemy persistence for dormant GitHub OAuth and browser sessions."""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Any, cast

from sqlalchemy import select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import BrowserSession, GithubOauthState
from app.modules.atomic.access.github_oauth_state import (
    ConsumedGithubOauthState,
    GithubOauthFlow,
    GithubOauthStateMaterial,
    digest_oauth_state,
)
from app.modules.atomic.access.server_session import (
    BrowserSessionRecord,
    digest_session_cookie,
)
from app.secrets import decrypt, encrypt


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


class SqlAlchemyGithubOauthStateRepository:
    """Persist state hashes and consume each callback state at most once."""

    def __init__(self, session: AsyncSession, *, encryption_keys: dict[str, str], active_key_id: str) -> None:
        if active_key_id not in encryption_keys:
            raise ValueError("active OAuth credential key is unavailable")
        self.session = session
        self.encryption_keys = dict(encryption_keys)
        self.active_key_id = active_key_id

    async def create(self, material: GithubOauthStateMaterial) -> None:
        self.session.add(
            GithubOauthState(
                id=material.state_id,
                state_digest=material.state_digest,
                browser_session_id=material.browser_session_id,
                flow_kind=material.flow_kind.value,
                return_path=material.return_path,
                pkce_verifier_encrypted=encrypt(material.pkce_verifier, self.encryption_keys[self.active_key_id]),
                credential_key_id=self.active_key_id,
                created_at=material.created_at,
                expires_at=material.expires_at,
            )
        )
        await self.session.commit()

    async def consume(
        self,
        state: str,
        *,
        browser_session_id: str,
        now: dt.datetime,
    ) -> ConsumedGithubOauthState | None:
        try:
            digest = digest_oauth_state(state)
        except ValueError:
            return None
        await self._begin_write()
        row = (
            await self.session.execute(
                select(GithubOauthState).where(
                    GithubOauthState.state_digest == digest,
                    GithubOauthState.browser_session_id == browser_session_id,
                    GithubOauthState.consumed_at.is_(None),
                    GithubOauthState.expires_at > now,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            await self.session.rollback()
            return None
        row.consumed_at = now
        await self.session.commit()
        key = self.encryption_keys.get(row.credential_key_id)
        verifier = decrypt(row.pkce_verifier_encrypted, key) if key is not None else None
        if verifier is None:
            return None
        return ConsumedGithubOauthState(
            pkce_verifier=verifier,
            flow_kind=GithubOauthFlow(row.flow_kind),
            return_path=row.return_path,
        )

    async def _begin_write(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))


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
    "SqlAlchemyGithubOauthStateRepository",
]
