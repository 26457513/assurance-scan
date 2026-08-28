"""Framework-free local-ingest quota contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class QuotaDecision(StrEnum):
    """Stable reasons a reservation may be rejected."""

    ALLOWED = "allowed"
    DISABLED = "disabled"
    TOKEN_HOURLY_RATE = "token_hourly_rate"
    USER_DAILY_RATE = "user_daily_rate"
    TOKEN_INFLIGHT = "token_inflight"
    USER_INFLIGHT = "user_inflight"
    INSTANCE_INFLIGHT = "instance_inflight"
    USER_RETAINED_STORAGE = "user_retained_storage"
    INSTANCE_RETAINED_STORAGE = "instance_retained_storage"
    USER_DAILY_BYTES = "user_daily_bytes"


@dataclass(frozen=True)
class QuotaCommand:
    """Usage that must be atomically reserved before accepting an upload."""

    user_id: int
    token_id: str
    client_request_id: str
    accepted_bytes: int
    enabled: bool = True


@dataclass(frozen=True)
class UsageSnapshot:
    """Existing committed and reserved usage at one serialized instant."""

    token_uploads_hour: int = 0
    user_uploads_day: int = 0
    token_inflight: int = 0
    user_inflight: int = 0
    instance_inflight: int = 0
    user_retained_bytes: int = 0
    instance_retained_bytes: int = 0
    user_accepted_bytes_day: int = 0


@dataclass(frozen=True)
class UsageReservation:
    """Opaque reservation identity returned by a persistence adapter."""

    user_id: int
    token_id: str
    client_request_id: str
    accepted_bytes: int
    reserved_at: datetime


@dataclass(frozen=True)
class QuotaResult:
    """Quota decision and reservation when capacity was atomically secured."""

    decision: QuotaDecision
    reservation: UsageReservation | None = None
    retry_after_seconds: int | None = None

    @property
    def allowed(self) -> bool:
        return self.decision is QuotaDecision.ALLOWED


__all__ = [
    "QuotaCommand",
    "QuotaDecision",
    "QuotaResult",
    "UsageReservation",
    "UsageSnapshot",
]
