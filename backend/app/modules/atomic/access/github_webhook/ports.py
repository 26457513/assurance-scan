"""Persistence port for GitHub webhook delivery idempotency."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import VerifiedGithubWebhook, WebhookClaimDecision


class GithubWebhookDeliveryRepositoryPort(Protocol):
    async def claim(
        self,
        webhook: VerifiedGithubWebhook,
        *,
        received_at: datetime,
        expires_at: datetime,
    ) -> WebhookClaimDecision: ...
