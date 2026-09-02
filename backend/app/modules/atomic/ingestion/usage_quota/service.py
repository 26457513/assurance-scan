"""Deterministic usage-limit policy and repository composition."""

from __future__ import annotations

from datetime import datetime

from app.modules.shared.contracts.local_scan import USAGE_LIMITS, UsageLimits
from app.modules.shared.contracts.ingest_v2 import (
    GITHUB_USAGE_LIMITS_V2,
    SHARED_USAGE_LIMITS_V2,
    GitHubUsageLimitsV2,
    SharedUsageLimitsV2,
)

from .models import (
    GithubQuotaCommand,
    GithubQuotaDecision,
    GithubQuotaResult,
    GithubUsageSnapshot,
    QuotaCommand,
    QuotaDecision,
    QuotaResult,
    UsageSnapshot,
)
from .ports import GithubUsageQuotaRepositoryPort, UsageQuotaRepositoryPort


def decide_usage_quota(
    command: QuotaCommand,
    snapshot: UsageSnapshot,
    *,
    limits: UsageLimits = USAGE_LIMITS,
) -> QuotaDecision:
    """Return the first violated limit in stable, inexpensive-first order."""
    _validate(command, snapshot)
    if not command.enabled:
        return QuotaDecision.DISABLED
    checks = (
        (snapshot.token_uploads_hour >= limits.uploads_per_token_hour, QuotaDecision.TOKEN_HOURLY_RATE),
        (snapshot.user_uploads_day >= limits.uploads_per_user_day, QuotaDecision.USER_DAILY_RATE),
        (snapshot.token_inflight >= limits.inflight_per_token, QuotaDecision.TOKEN_INFLIGHT),
        (snapshot.user_inflight >= limits.inflight_per_user, QuotaDecision.USER_INFLIGHT),
        (snapshot.instance_inflight >= limits.inflight_per_instance, QuotaDecision.INSTANCE_INFLIGHT),
        (
            snapshot.shared_instance_inflight >= SHARED_USAGE_LIMITS_V2.inflight_per_instance,
            QuotaDecision.SHARED_INSTANCE_INFLIGHT,
        ),
        (
            snapshot.user_retained_bytes + command.accepted_bytes > limits.retained_bytes_per_user,
            QuotaDecision.USER_RETAINED_STORAGE,
        ),
        (
            snapshot.instance_retained_bytes + command.accepted_bytes > limits.retained_bytes_per_instance,
            QuotaDecision.INSTANCE_RETAINED_STORAGE,
        ),
        (
            snapshot.user_accepted_bytes_day + command.accepted_bytes > limits.accepted_bytes_per_user_day,
            QuotaDecision.USER_DAILY_BYTES,
        ),
    )
    return next((decision for exceeded, decision in checks if exceeded), QuotaDecision.ALLOWED)


async def reserve_usage(
    command: QuotaCommand,
    *,
    repository: UsageQuotaRepositoryPort,
    now: datetime,
    limits: UsageLimits = USAGE_LIMITS,
) -> QuotaResult:
    """Atomically enforce the policy through the configured repository."""
    _validate(command, UsageSnapshot())
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("quota timestamp must be timezone-aware")
    if not command.enabled:
        return QuotaResult(QuotaDecision.DISABLED)
    return await repository.reserve(command, limits=limits, now=now)


def decide_github_usage_quota(
    command: GithubQuotaCommand,
    snapshot: GithubUsageSnapshot,
    *,
    limits: GitHubUsageLimitsV2 = GITHUB_USAGE_LIMITS_V2,
    shared_limits: SharedUsageLimitsV2 = SHARED_USAGE_LIMITS_V2,
) -> GithubQuotaDecision:
    """Return the first violated GitHub/shared limit in stable order."""
    _validate_github(command, snapshot)
    checks = (
        (
            snapshot.repository_uploads_hour >= limits.uploads_per_repository_hour,
            GithubQuotaDecision.REPOSITORY_HOURLY_RATE,
        ),
        (
            snapshot.owner_uploads_day >= limits.uploads_per_owner_day,
            GithubQuotaDecision.OWNER_DAILY_RATE,
        ),
        (
            snapshot.repository_inflight >= limits.inflight_per_repository,
            GithubQuotaDecision.REPOSITORY_INFLIGHT,
        ),
        (
            snapshot.instance_inflight >= shared_limits.inflight_per_instance,
            GithubQuotaDecision.INSTANCE_INFLIGHT,
        ),
        (
            snapshot.owner_accepted_bytes_day + command.accepted_bytes > limits.accepted_bytes_per_owner_day,
            GithubQuotaDecision.OWNER_DAILY_BYTES,
        ),
    )
    return next(
        (decision for exceeded, decision in checks if exceeded),
        GithubQuotaDecision.ALLOWED,
    )


async def reserve_github_usage(
    command: GithubQuotaCommand,
    *,
    repository: GithubUsageQuotaRepositoryPort,
    now: datetime,
    limits: GitHubUsageLimitsV2 = GITHUB_USAGE_LIMITS_V2,
    shared_limits: SharedUsageLimitsV2 = SHARED_USAGE_LIMITS_V2,
) -> GithubQuotaResult:
    """Atomically reserve GitHub and shared upload capacity."""
    _validate_github(command, GithubUsageSnapshot())
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("quota timestamp must be timezone-aware")
    return await repository.reserve(
        command,
        limits=limits,
        shared_limits=shared_limits,
        now=now,
    )


def _validate(command: QuotaCommand, snapshot: UsageSnapshot) -> None:
    if command.user_id <= 0 or not command.token_id or not command.client_request_id:
        raise ValueError("quota identity fields must be present")
    values = (command.accepted_bytes, *snapshot.__dict__.values())
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
        raise ValueError("quota byte and counter values must be non-negative integers")


def _validate_github(command: GithubQuotaCommand, snapshot: GithubUsageSnapshot) -> None:
    identifiers = (
        command.project_id,
        command.github_repository_id,
        command.github_owner_id,
        command.github_run_id,
        command.run_attempt,
    )
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in identifiers):
        raise ValueError("GitHub quota identity fields must be positive integers")
    counters = (command.accepted_bytes, *snapshot.__dict__.values())
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counters):
        raise ValueError("GitHub quota byte and counter values must be non-negative integers")


__all__ = [
    "decide_github_usage_quota",
    "decide_usage_quota",
    "reserve_github_usage",
    "reserve_usage",
]
