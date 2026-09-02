"""Transactional replay-evidence store for GitHub Actions OIDC JWTs."""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import GithubOidcReplay


class SqlAlchemyGithubOidcReplayRepository:
    """Use the unique JTI digest as the cross-worker replay fence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def consume(
        self,
        *,
        jti_digest: bytes,
        repository_id: int,
        consumed_at: dt.datetime,
        expires_at: dt.datetime,
    ) -> bool:
        if self.session.in_transaction():
            raise RuntimeError("OIDC replay consumption requires a clean session")
        self.session.add(
            GithubOidcReplay(
                jti_digest=jti_digest,
                github_repository_id=repository_id,
                consumed_at=consumed_at,
                expires_at=expires_at,
            )
        )
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            return False
        return True

    async def purge_expired(self, *, now: dt.datetime) -> int:
        result = cast(CursorResult[Any], await self.session.execute(
            delete(GithubOidcReplay).where(GithubOidcReplay.expires_at <= now)
        ))
        await self.session.commit()
        return int(result.rowcount or 0)


__all__ = ["SqlAlchemyGithubOidcReplayRepository"]
