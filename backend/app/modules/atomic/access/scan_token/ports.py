"""Abstract ports required by the scan-token capability."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import (
    ScanTokenAuthenticationRecord,
    ScanTokenCreateStorageDecision,
    ScanTokenRecord,
)


class ScanTokenClockPort(Protocol):
    """Supply the current timezone-aware time."""

    def now(self) -> datetime: ...


class ScanTokenRandomPort(Protocol):
    """Supply cryptographically secure random bytes in production."""

    def random_bytes(self, size: int) -> bytes: ...


class ScanTokenRepositoryPort(Protocol):
    """Persistence operations with transactional issuance enforcement."""

    async def create_token(
        self,
        record: ScanTokenRecord,
        *,
        now: datetime,
        active_limit: int,
        creation_hourly_limit: int,
    ) -> ScanTokenCreateStorageDecision: ...

    async def find_for_authentication(
        self,
        selector: str,
    ) -> ScanTokenAuthenticationRecord | None: ...


__all__ = [
    "ScanTokenClockPort",
    "ScanTokenRandomPort",
    "ScanTokenRepositoryPort",
]
