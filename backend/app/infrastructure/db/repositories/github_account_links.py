"""Transactional adapter for immutable GitHub account links."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import GithubAccount, ProjectMembership, User
from app.modules.atomic.access.github_account_link import (
    GithubAccountLinkDecision,
    LinkGithubAccountCommand,
)
from app.modules.atomic.access.github_membership_projection import (
    GithubMembershipProjection,
    validate_membership_projection,
)
from app.secrets import encrypt


class SqlAlchemyGithubAccountLinkRepository:
    """Serialize links and encrypt credentials before persistence."""

    def __init__(self, session: AsyncSession, *, encryption_key: str, key_id: str) -> None:
        if not encryption_key or not key_id:
            raise ValueError("GitHub credential encryption is not configured")
        self.session = session
        self.encryption_key = encryption_key
        self.key_id = key_id

    async def link(self, command: LinkGithubAccountCommand, *, linked_at: dt.datetime) -> GithubAccountLinkDecision:
        await self._begin_write()
        user = await self.session.get(User, command.user_id)
        if user is None or user.disabled_at is not None:
            await self.session.rollback()
            return GithubAccountLinkDecision.USER_ALREADY_LINKED
        github_owner = (
            await self.session.execute(
                select(GithubAccount).where(GithubAccount.github_user_id == command.github_user_id)
            )
        ).scalar_one_or_none()
        if github_owner is not None and github_owner.user_id != command.user_id:
            await self.session.rollback()
            return GithubAccountLinkDecision.IDENTITY_COLLISION
        user_link = (
            await self.session.execute(select(GithubAccount).where(GithubAccount.user_id == command.user_id))
        ).scalar_one_or_none()
        if user_link is not None and user_link.github_user_id != command.github_user_id:
            await self.session.rollback()
            return GithubAccountLinkDecision.USER_ALREADY_LINKED
        row = user_link or github_owner
        if row is None:
            row = GithubAccount(email=None, token_encrypted=None, created_at=linked_at)
            self.session.add(row)
        row.user_id = command.user_id
        row.github_user_id = command.github_user_id
        row.login_at_last_verify = command.login
        row.encrypted_user_token = encrypt(command.user_token, self.encryption_key)
        row.encrypted_refresh_token = (
            encrypt(command.refresh_token, self.encryption_key) if command.refresh_token is not None else None
        )
        row.credential_key_id = self.key_id
        row.token_expires_at = command.token_expires_at
        row.linked_at = row.linked_at or linked_at
        row.verified_at = command.verified_at or linked_at
        row.disconnected_at = None
        await self.session.commit()
        return GithubAccountLinkDecision.LINKED

    async def _begin_write(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))


class SqlAlchemyGithubMembershipProjectionRepository:
    """Replace only GitHub App-derived rows, preserving manual/legacy rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_for_user(
        self,
        user_id: int,
        rows: tuple[GithubMembershipProjection, ...],
    ) -> None:
        projections = validate_membership_projection(rows)
        if self.session.in_transaction():
            await self.session.rollback()
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))
        await self.session.execute(
            delete(ProjectMembership).where(
                ProjectMembership.user_id == user_id,
                ProjectMembership.source == "github_app",
            )
        )
        self.session.add_all(
            [
                ProjectMembership(
                    user_id=user_id,
                    project_id=row.project_id,
                    permission=row.permission.value,
                    source="github_app",
                    verified_at=row.verified_at,
                    expires_at=row.expires_at,
                )
                for row in projections
            ]
        )
        await self.session.commit()


__all__ = [
    "SqlAlchemyGithubAccountLinkRepository",
    "SqlAlchemyGithubMembershipProjectionRepository",
]
