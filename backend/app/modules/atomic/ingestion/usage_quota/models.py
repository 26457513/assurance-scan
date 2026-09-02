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
    SHARED_INSTANCE_INFLIGHT = "shared_instance_inflight"
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
    project_id: int = 0
    payload_hash: str = ""
    correlation_id: str = ""


@dataclass(frozen=True)
class UsageSnapshot:
    """Existing committed and reserved usage at one serialized instant."""

    token_uploads_hour: int = 0
    user_uploads_day: int = 0
    token_inflight: int = 0
    user_inflight: int = 0
    instance_inflight: int = 0
    shared_instance_inflight: int = 0
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


class GithubQuotaDecision(StrEnum):
    ALLOWED = "allowed"
    REPOSITORY_HOURLY_RATE = "repository_hourly_rate"
    OWNER_DAILY_RATE = "owner_daily_rate"
    REPOSITORY_INFLIGHT = "repository_inflight"
    INSTANCE_INFLIGHT = "instance_inflight"
    OWNER_DAILY_BYTES = "owner_daily_bytes"


@dataclass(frozen=True)
class GithubQuotaCommand:
    project_id: int
    github_repository_id: int
    github_owner_id: int
    github_run_id: int
    run_attempt: int
    accepted_bytes: int
    payload_hash: str = ""
    correlation_id: str = ""


@dataclass(frozen=True)
class GithubUsageSnapshot:
    repository_uploads_hour: int = 0
    owner_uploads_day: int = 0
    repository_inflight: int = 0
    instance_inflight: int = 0
    owner_accepted_bytes_day: int = 0


@dataclass(frozen=True)
class GithubUsageReservation:
    github_repository_id: int
    github_owner_id: int
    github_run_id: int
    run_attempt: int
    accepted_bytes: int
    reserved_at: datetime


@dataclass(frozen=True)
class GithubQuotaResult:
    decision: GithubQuotaDecision
    reservation: GithubUsageReservation | None = None
    retry_after_seconds: int | None = None

    @property
    def allowed(self) -> bool:
        return self.decision is GithubQuotaDecision.ALLOWED


__all__ = [
    "QuotaCommand",
    "QuotaDecision",
    "QuotaResult",
    "UsageReservation",
    "UsageSnapshot",
    "GithubQuotaCommand",
    "GithubQuotaDecision",
    "GithubQuotaResult",
    "GithubUsageReservation",
    "GithubUsageSnapshot",
]
