"""Persistence boundary for serialized usage reservations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.modules.shared.contracts.ingest_v2 import GitHubUsageLimitsV2, SharedUsageLimitsV2
from app.modules.shared.contracts.local_scan import UsageLimits

from .models import (
    GithubQuotaCommand,
    GithubQuotaResult,
    GithubUsageReservation,
    QuotaCommand,
    QuotaResult,
    UsageReservation,
)


class UsageQuotaRepositoryPort(Protocol):
    """Reserve usage atomically; implementations must serialize check + write."""

    async def reserve(
        self,
        command: QuotaCommand,
        *,
        limits: UsageLimits,
        now: datetime,
    ) -> QuotaResult: ...

    async def release(self, reservation: UsageReservation, *, now: datetime) -> bool: ...


class GithubUsageQuotaRepositoryPort(Protocol):
    async def reserve(
        self,
        command: GithubQuotaCommand,
        *,
        limits: GitHubUsageLimitsV2,
        shared_limits: SharedUsageLimitsV2,
        now: datetime,
    ) -> GithubQuotaResult: ...

    async def release(
        self,
        reservation: GithubUsageReservation,
        *,
        now: datetime,
    ) -> bool: ...


__all__ = ["GithubUsageQuotaRepositoryPort", "UsageQuotaRepositoryPort"]
