"""Deterministic usage-limit policy and repository composition."""

from __future__ import annotations

from datetime import datetime

from app.modules.shared.contracts.local_scan import USAGE_LIMITS, UsageLimits

from .models import QuotaCommand, QuotaDecision, QuotaResult, UsageSnapshot
from .ports import UsageQuotaRepositoryPort


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
            snapshot.user_retained_bytes + command.accepted_bytes > limits.retained_bytes_per_user,
            QuotaDecision.USER_RETAINED_STORAGE,
        ),
        (
            snapshot.instance_retained_bytes + command.accepted_bytes > limits.retained_bytes_per_instance,
            QuotaDecision.INSTANCE_RETAINED_STORAGE,
        ),
        (
            snapshot.user_accepted_bytes_day + command.accepted_bytes
            > limits.accepted_bytes_per_user_day,
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


def _validate(command: QuotaCommand, snapshot: UsageSnapshot) -> None:
    if command.user_id <= 0 or not command.token_id or not command.client_request_id:
        raise ValueError("quota identity fields must be present")
    values = (command.accepted_bytes, *snapshot.__dict__.values())
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
        raise ValueError("quota byte and counter values must be non-negative integers")


__all__ = ["decide_usage_quota", "reserve_usage"]
