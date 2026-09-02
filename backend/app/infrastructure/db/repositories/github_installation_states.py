"""Single-use persistence adapter for GitHub App installation setup state."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import GithubInstallationState
from app.modules.atomic.access.github_installation_state import (
    ConsumedGithubInstallationState,
    GithubInstallationStateMaterial,
    digest_installation_state,
)


class SqlAlchemyGithubInstallationStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, material: GithubInstallationStateMaterial) -> None:
        self.session.add(
            GithubInstallationState(
                id=material.state_id,
                state_digest=material.state_digest,
                browser_session_id=material.browser_session_id,
                return_path=material.return_path,
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
    ) -> ConsumedGithubInstallationState | None:
        try:
            digest = digest_installation_state(state)
        except ValueError:
            return None
        if self.session.in_transaction():
            await self.session.rollback()
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))
        row = (
            await self.session.execute(
                select(GithubInstallationState).where(
                    GithubInstallationState.state_digest == digest,
                    GithubInstallationState.browser_session_id == browser_session_id,
                    GithubInstallationState.consumed_at.is_(None),
                    GithubInstallationState.expires_at > now,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            await self.session.rollback()
            return None
        return_path = row.return_path
        row.consumed_at = now
        await self.session.commit()
        return ConsumedGithubInstallationState(return_path=return_path)


__all__ = ["SqlAlchemyGithubInstallationStateRepository"]
