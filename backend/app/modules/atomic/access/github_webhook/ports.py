"""Persistence port for GitHub webhook delivery idempotency."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import GithubWebhookWorkLease, VerifiedGithubWebhook, WebhookClaimDecision


class GithubWebhookDeliveryRepositoryPort(Protocol):
    async def claim(
        self,
        webhook: VerifiedGithubWebhook,
        *,
        received_at: datetime,
        expires_at: datetime,
    ) -> WebhookClaimDecision: ...

    async def lease_next(
        self,
        *,
        now: datetime,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> GithubWebhookWorkLease | None: ...

    async def complete(self, lease: GithubWebhookWorkLease, *, processed_at: datetime) -> bool: ...

    async def renew(
        self,
        lease: GithubWebhookWorkLease,
        *,
        renewed_at: datetime,
        lease_expires_at: datetime,
    ) -> bool: ...

    async def retry(
        self,
        lease: GithubWebhookWorkLease,
        *,
        available_at: datetime,
        failed_at: datetime,
        error_code: str,
        terminal: bool,
    ) -> bool: ...
