"""Lifecycle adapter for encrypted, expiring GitHub App user credentials."""

from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.infrastructure.db.models import GithubAccount
from app.infrastructure.github_oauth import refresh_and_verify_github_authorization
from app.secrets import decrypt, encrypt


_REFRESH_MARGIN = dt.timedelta(minutes=2)
_refresh_locks: dict[int, asyncio.Lock] = {}


async def usable_github_access_token(
    session: AsyncSession,
    *,
    user_id: int,
    settings: Settings,
    now: dt.datetime,
) -> str | None:
    """Return a current token, rotating it once near expiry and failing closed.

    The caller owns the session transaction. In particular, resolving a token
    must not roll back identity objects or unrelated pending work loaded by the
    request dependency graph.
    """
    lock = _refresh_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        account = (
            await session.execute(
                select(GithubAccount).where(
                    GithubAccount.user_id == user_id,
                    GithubAccount.disconnected_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if account is None or account.encrypted_user_token is None:
            return None
        access_token = decrypt(account.encrypted_user_token, settings.token_encryption_key)
        expires_at = _aware(account.token_expires_at)
        if access_token and expires_at is not None and expires_at > now + _REFRESH_MARGIN:
            return access_token
        refresh_token = decrypt(
            account.encrypted_refresh_token or "",
            settings.token_encryption_key,
        )
        if not refresh_token:
            return None
        try:
            authorization = await asyncio.to_thread(
                refresh_and_verify_github_authorization,
                refresh_token=refresh_token,
                client_id=settings.github_app_client_id,
                client_secret=settings.github_app_client_secret,
            )
        except (OSError, RuntimeError, ValueError):
            return None
        if authorization.github_user_id != account.github_user_id:
            return None
        account.login_at_last_verify = authorization.login
        account.encrypted_user_token = encrypt(
            authorization.access_token,
            settings.token_encryption_key,
        )
        account.encrypted_refresh_token = encrypt(
            authorization.refresh_token,
            settings.token_encryption_key,
        )
        account.credential_key_id = "primary"
        account.token_expires_at = now + dt.timedelta(seconds=authorization.expires_in_seconds)
        account.verified_at = now
        await session.commit()
        return authorization.access_token


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value


__all__ = ["usable_github_access_token"]
