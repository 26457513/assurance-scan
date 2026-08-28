"""SQLAlchemy adapter for the atomic scan-token persistence port."""

from __future__ import annotations

import datetime as dt
import secrets
from collections.abc import Sequence

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import ApiToken, User
from app.modules.atomic.access.scan_token import (
    ScanTokenAuthenticationRecord,
    ScanTokenCreateStorageDecision,
    ScanTokenRecord,
)


class SystemScanTokenClock:
    """Production UTC clock adapter."""

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)


class SecureScanTokenRandom:
    """Production CSPRNG adapter."""

    def random_bytes(self, size: int) -> bytes:
        return secrets.token_bytes(size)


class SqlAlchemyScanTokenRepository:
    """Persist tokens while serializing active-limit and label decisions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_token(
        self,
        record: ScanTokenRecord,
        *,
        now: dt.datetime,
        active_limit: int,
        creation_hourly_limit: int,
    ) -> ScanTokenCreateStorageDecision:
        await self._begin_user_write(record.user_id)
        active_predicates = (
            ApiToken.user_id == record.user_id,
            ApiToken.revoked_at.is_(None),
            ApiToken.expires_at > now,
        )
        active_count = int(
            (
                await self.session.execute(select(func.count()).select_from(ApiToken).where(*active_predicates))
            ).scalar_one()
        )
        if active_count >= active_limit:
            await self.session.rollback()
            return ScanTokenCreateStorageDecision.ACTIVE_LIMIT_REACHED
        creation_count = int(
            (
                await self.session.execute(
                    select(func.count())
                    .select_from(ApiToken)
                    .where(
                        ApiToken.user_id == record.user_id,
                        ApiToken.created_at >= now - dt.timedelta(hours=1),
                    )
                )
            ).scalar_one()
        )
        if creation_count >= creation_hourly_limit:
            await self.session.rollback()
            return ScanTokenCreateStorageDecision.CREATION_RATE_LIMITED
        label_exists = (
            await self.session.execute(
                select(ApiToken.id).where(
                    *active_predicates,
                    ApiToken.label_key == record.label_key,
                )
            )
        ).scalar_one_or_none()
        if label_exists is not None:
            await self.session.rollback()
            return ScanTokenCreateStorageDecision.LABEL_CONFLICT

        self.session.add(
            ApiToken(
                id=record.token_id,
                user_id=record.user_id,
                label=record.label,
                label_key=record.label_key,
                selector=record.selector,
                secret_digest=record.secret_digest,
                scope=record.scope,
                token_version=record.token_version,
                created_at=record.created_at,
                expires_at=record.expires_at,
                revoked_at=record.revoked_at,
            )
        )
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            if await self._selector_or_id_exists(record):
                return ScanTokenCreateStorageDecision.SELECTOR_COLLISION
            if await self._active_label_exists(record, now):
                return ScanTokenCreateStorageDecision.LABEL_CONFLICT
            raise
        return ScanTokenCreateStorageDecision.CREATED

    async def find_for_authentication(
        self,
        selector: str,
    ) -> ScanTokenAuthenticationRecord | None:
        row = (
            await self.session.execute(
                select(ApiToken, User).join(User, User.id == ApiToken.user_id).where(ApiToken.selector == selector)
            )
        ).first()
        if row is None:
            return None
        token, user = row
        return ScanTokenAuthenticationRecord(
            token=_to_record(token),
            user_email=user.email,
            user_disabled_at=_aware_or_none(user.disabled_at),
        )

    async def list_for_user(self, user_id: int) -> Sequence[ApiToken]:
        return tuple(
            (
                await self.session.execute(
                    select(ApiToken)
                    .where(ApiToken.user_id == user_id)
                    .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
                )
            ).scalars()
        )

    async def revoke_owned(
        self,
        *,
        user_id: int,
        token_id: str,
        now: dt.datetime,
    ) -> bool:
        await self._begin_user_write(user_id)
        token = (
            await self.session.execute(
                select(ApiToken).where(
                    ApiToken.id == token_id,
                    ApiToken.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        changed = False
        if token is not None and token.revoked_at is None:
            token.revoked_at = now
            changed = True
        await self.session.commit()
        return changed

    async def touch_last_used(
        self,
        token_id: str,
        *,
        now: dt.datetime,
        minimum_interval: dt.timedelta = dt.timedelta(hours=1),
    ) -> None:
        """Best-effort throttled audit update after successful authentication."""
        try:
            token = await self.session.get(ApiToken, token_id)
            if token is None:
                return
            last_used = _aware_or_none(token.last_used_at)
            if last_used is None or last_used <= now - minimum_interval:
                token.last_used_at = now
                await self.session.commit()
            else:
                await self.session.rollback()
        except Exception:
            await self.session.rollback()

    async def _begin_user_write(self, user_id: int) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
        dialect = self.session.get_bind().dialect.name
        if dialect == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))
            return
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())

    async def _selector_or_id_exists(self, record: ScanTokenRecord) -> bool:
        existing = (
            await self.session.execute(
                select(ApiToken.id).where((ApiToken.selector == record.selector) | (ApiToken.id == record.token_id))
            )
        ).first()
        return existing is not None

    async def _active_label_exists(
        self,
        record: ScanTokenRecord,
        now: dt.datetime,
    ) -> bool:
        existing = (
            await self.session.execute(
                select(ApiToken.id).where(
                    ApiToken.user_id == record.user_id,
                    ApiToken.label_key == record.label_key,
                    ApiToken.revoked_at.is_(None),
                    ApiToken.expires_at > now,
                )
            )
        ).first()
        return existing is not None


def _to_record(row: ApiToken) -> ScanTokenRecord:
    return ScanTokenRecord(
        token_id=row.id,
        user_id=row.user_id,
        label=row.label,
        label_key=row.label_key,
        selector=row.selector,
        secret_digest=bytes(row.secret_digest),
        scope=row.scope,
        token_version=row.token_version,
        created_at=_aware(row.created_at),
        expires_at=_aware(row.expires_at),
        revoked_at=_aware_or_none(row.revoked_at),
    )


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value


def _aware_or_none(value: dt.datetime | None) -> dt.datetime | None:
    return _aware(value) if value is not None else None


__all__ = [
    "SecureScanTokenRandom",
    "SqlAlchemyScanTokenRepository",
    "SystemScanTokenClock",
]
