"""Persistence for pre-authentication state and immutable GitHub identities."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import GithubAccount, GithubSigninState, User
from app.infrastructure.github_oauth import VerifiedGithubAuthorization
from app.modules.atomic.access.github_signin_transaction import (
    ConsumedGithubSignin,
    GithubSigninMaterial,
    digest_signin_value,
)
from app.secrets import decrypt, encrypt


class SqlAlchemyGithubSigninRepository:
    def __init__(self, session: AsyncSession, *, encryption_key: str, key_id: str = "primary") -> None:
        if not encryption_key:
            raise ValueError("GitHub credential encryption is not configured")
        self.session = session
        self.encryption_key = encryption_key
        self.key_id = key_id

    async def create(self, material: GithubSigninMaterial) -> None:
        self.session.add(
            GithubSigninState(
                id=material.transaction_id,
                state_digest=material.state_digest,
                transaction_digest=material.transaction_digest,
                return_path=material.return_path,
                pkce_verifier_encrypted=encrypt(material.pkce_verifier, self.encryption_key),
                credential_key_id=self.key_id,
                created_at=material.created_at,
                expires_at=material.expires_at,
            )
        )
        await self.session.commit()

    async def consume(
        self, *, state: str, transaction_cookie: str, now: dt.datetime
    ) -> ConsumedGithubSignin | None:
        try:
            state_digest = digest_signin_value(state)
            transaction_digest = digest_signin_value(transaction_cookie)
        except ValueError:
            return None
        await self._begin_write()
        row = (
            await self.session.execute(
                select(GithubSigninState).where(
                    GithubSigninState.state_digest == state_digest,
                    GithubSigninState.transaction_digest == transaction_digest,
                    GithubSigninState.consumed_at.is_(None),
                    GithubSigninState.expires_at > now,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            await self.session.rollback()
            return None
        row.consumed_at = now
        await self.session.commit()
        verifier = decrypt(row.pkce_verifier_encrypted, self.encryption_key)
        return ConsumedGithubSignin(pkce_verifier=verifier, return_path=row.return_path) if verifier else None

    async def resolve_user(
        self,
        authorization: VerifiedGithubAuthorization,
        *,
        now: dt.datetime,
        admin_github_ids: frozenset[int],
    ) -> User:
        await self._begin_write()
        account = (
            await self.session.execute(
                select(GithubAccount).where(GithubAccount.github_user_id == authorization.github_user_id)
            )
        ).scalar_one_or_none()
        if account is None:
            user = User(
                email=None,
                github_login=authorization.login,
                role="admin" if authorization.github_user_id in admin_github_ids else "user",
                created_at=now,
                last_login_at=now,
            )
            self.session.add(user)
            await self.session.flush()
            account = GithubAccount(
                created_at=now,
                user_id=user.id,
                github_user_id=authorization.github_user_id,
                linked_at=now,
            )
            self.session.add(account)
        else:
            existing_user = await self.session.get(User, account.user_id)
            if existing_user is None:
                await self.session.rollback()
                raise RuntimeError("GitHub identity has no account")
            if existing_user.disabled_at is not None:
                await self.session.rollback()
                raise PermissionError("account is disabled")
            user = existing_user
            user.github_login = authorization.login
            user.last_login_at = now
        account.login_at_last_verify = authorization.login
        account.encrypted_user_token = encrypt(authorization.access_token, self.encryption_key)
        account.encrypted_refresh_token = encrypt(authorization.refresh_token, self.encryption_key)
        account.credential_key_id = self.key_id
        account.token_expires_at = now + dt.timedelta(seconds=authorization.expires_in_seconds)
        account.verified_at = now
        account.disconnected_at = None
        await self.session.commit()
        return user

    async def _begin_write(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
        bind: Any = self.session.get_bind()
        if bind.dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))
