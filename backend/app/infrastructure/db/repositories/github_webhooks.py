"""Transactional idempotency adapter for authenticated GitHub webhooks."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import GithubWebhookDelivery
from app.modules.atomic.access.github_webhook import (
    VerifiedGithubWebhook,
    WebhookClaimDecision,
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
                status="received" if webhook.mutation_allowed else "acknowledged",
                received_at=received_at,
                processed_at=received_at if not webhook.mutation_allowed else None,
                expires_at=expires_at,
            )
        )
        await self.session.commit()
        return WebhookClaimDecision.ACQUIRED


__all__ = ["SqlAlchemyGithubWebhookDeliveryRepository"]
