"""Transactional idempotency adapter for authenticated GitHub webhooks."""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from sqlalchemy import or_, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import GithubWebhookDelivery
from app.modules.atomic.access.github_webhook import (
    VerifiedGithubWebhook,
    WebhookClaimDecision,
    GithubWebhookWorkLease,
)


class SqlAlchemyGithubWebhookDeliveryRepository:
    """Atomically distinguish a new delivery, replay, and body-hash conflict."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(
        self,
        webhook: VerifiedGithubWebhook,
        *,
        received_at: dt.datetime,
        expires_at: dt.datetime,
    ) -> WebhookClaimDecision:
        if self.session.in_transaction():
            await self.session.rollback()
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))
        existing = await self.session.get(GithubWebhookDelivery, webhook.delivery_id)
        if existing is not None:
            body_matches = existing.body_hash == webhook.body_hash
            await self.session.rollback()
            if body_matches:
                return WebhookClaimDecision.REPLAY
            return WebhookClaimDecision.CONFLICT
        self.session.add(
            GithubWebhookDelivery(
                delivery_id=webhook.delivery_id,
                body_hash=webhook.body_hash,
                event=webhook.event,
                action=webhook.action,
                github_installation_id=webhook.github_installation_id,
                status="received" if webhook.mutation_allowed else "acknowledged",
                attempt_count=0,
                available_at=received_at if webhook.mutation_allowed else None,
                lease_token=None,
                lease_expires_at=None,
                last_error_code=None,
                received_at=received_at,
                processed_at=received_at if not webhook.mutation_allowed else None,
                expires_at=expires_at,
            )
        )
        await self.session.commit()
        return WebhookClaimDecision.ACQUIRED

    async def lease_next(
        self,
        *,
        now: dt.datetime,
        lease_token: str,
        lease_expires_at: dt.datetime,
    ) -> GithubWebhookWorkLease | None:
        await self._begin_write()
        try:
            statement = (
                select(GithubWebhookDelivery)
                .where(
                    GithubWebhookDelivery.status == "received",
                    GithubWebhookDelivery.github_installation_id.isnot(None),
                    GithubWebhookDelivery.available_at.isnot(None),
                    GithubWebhookDelivery.available_at <= now,
                    or_(
                        GithubWebhookDelivery.lease_expires_at.is_(None),
                        GithubWebhookDelivery.lease_expires_at <= now,
                    ),
                )
                .order_by(GithubWebhookDelivery.received_at, GithubWebhookDelivery.delivery_id)
                .limit(1)
            )
            if self.session.get_bind().dialect.name != "sqlite":
                statement = statement.with_for_update(skip_locked=True)
            row = (await self.session.execute(statement)).scalar_one_or_none()
            if row is None or row.github_installation_id is None:
                await self.session.rollback()
                return None
            row.lease_token = lease_token
            row.lease_expires_at = lease_expires_at
            row.attempt_count += 1
            row.last_error_code = None
            lease = GithubWebhookWorkLease(
                delivery_id=row.delivery_id,
                github_installation_id=row.github_installation_id,
                event=row.event,
                action=row.action,
                lease_token=lease_token,
                attempt_count=row.attempt_count,
            )
            await self.session.commit()
            return lease
        except Exception:
            await self.session.rollback()
            raise

    async def complete(self, lease: GithubWebhookWorkLease, *, processed_at: dt.datetime) -> bool:
        await self._begin_write()
        try:
            result = await self.session.execute(
                update(GithubWebhookDelivery)
                .where(
                    GithubWebhookDelivery.delivery_id == lease.delivery_id,
                    GithubWebhookDelivery.status == "received",
                    GithubWebhookDelivery.lease_token == lease.lease_token,
                    GithubWebhookDelivery.lease_expires_at > processed_at,
                )
                .values(
                    status="processed",
                    processed_at=processed_at,
                    lease_token=None,
                    lease_expires_at=None,
                    last_error_code=None,
                )
            )
            await self.session.commit()
            return cast(CursorResult[Any], result).rowcount == 1
        except Exception:
            await self.session.rollback()
            raise

    async def renew(
        self,
        lease: GithubWebhookWorkLease,
        *,
        renewed_at: dt.datetime,
        lease_expires_at: dt.datetime,
    ) -> bool:
        await self._begin_write()
        try:
            result = await self.session.execute(
                update(GithubWebhookDelivery)
                .where(
                    GithubWebhookDelivery.delivery_id == lease.delivery_id,
                    GithubWebhookDelivery.status == "received",
                    GithubWebhookDelivery.lease_token == lease.lease_token,
                    GithubWebhookDelivery.lease_expires_at > renewed_at,
                )
                .values(lease_expires_at=lease_expires_at)
            )
            await self.session.commit()
            return cast(CursorResult[Any], result).rowcount == 1
        except Exception:
            await self.session.rollback()
            raise

    async def retry(
        self,
        lease: GithubWebhookWorkLease,
        *,
        available_at: dt.datetime,
        failed_at: dt.datetime,
        error_code: str,
        terminal: bool,
    ) -> bool:
        await self._begin_write()
        try:
            result = await self.session.execute(
                update(GithubWebhookDelivery)
                .where(
                    GithubWebhookDelivery.delivery_id == lease.delivery_id,
                    GithubWebhookDelivery.status == "received",
                    GithubWebhookDelivery.lease_token == lease.lease_token,
                )
                .values(
                    status="failed" if terminal else "received",
                    processed_at=failed_at if terminal else None,
                    available_at=available_at,
                    lease_token=None,
                    lease_expires_at=None,
                    last_error_code=error_code,
                )
            )
            await self.session.commit()
            return cast(CursorResult[Any], result).rowcount == 1
        except Exception:
            await self.session.rollback()
            raise

    async def _begin_write(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))


__all__ = ["SqlAlchemyGithubWebhookDeliveryRepository"]
