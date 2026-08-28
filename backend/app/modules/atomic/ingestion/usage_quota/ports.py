"""Persistence boundary for serialized usage reservations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.modules.shared.contracts.local_scan import UsageLimits

from .models import QuotaCommand, QuotaResult, UsageReservation


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


__all__ = ["UsageQuotaRepositoryPort"]
