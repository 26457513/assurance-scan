"""Raw-body authentication and idempotency orchestration for GitHub webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from app.modules.shared.contracts.ingest_v2 import WEBHOOK_EVENT_ACTIONS, WEBHOOK_POLICY_V2

from .models import (
    GithubWebhookError,
    GithubWebhookErrorCode,
    GithubWebhookSecrets,
    GithubWebhookWorkLease,
    VerifiedGithubWebhook,
    WebhookClaimDecision,
)
from .ports import GithubWebhookDeliveryRepositoryPort


_SIGNATURE = re.compile(r"^sha256=([0-9a-f]{64})$")
_EVENT = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ALLOWED = frozenset(WEBHOOK_EVENT_ACTIONS)
_WORK_LEASE = timedelta(minutes=5)
_MAXIMUM_WORK_ATTEMPTS = 8
_INITIAL_RETRY_SECONDS = 30
_MAXIMUM_RETRY_SECONDS = 60 * 60


def verify_github_webhook(
    raw_body: bytes,
    *,
    content_type: str,
    delivery_id: str,
    event: str,
    signature: str,
    secrets: GithubWebhookSecrets,
    now: datetime,
) -> VerifiedGithubWebhook:
    """Authenticate exact bytes before parsing and classify the event action."""
    if len(raw_body) > WEBHOOK_POLICY_V2.maximum_body_bytes:
        raise GithubWebhookError(GithubWebhookErrorCode.BODY_TOO_LARGE)
    if content_type.partition(";")[0].strip().casefold() != "application/json":
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_CONTENT_TYPE)
    canonical_delivery_id = _delivery_id(delivery_id)
    if _EVENT.fullmatch(event) is None:
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_EVENT)
    aware_now = _aware(now)
    if not secrets.current:
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_SIGNATURE)
    supplied = _signature_digest(signature)
    current_digest = hmac.new(secrets.current, raw_body, hashlib.sha256).hexdigest()
    current_match = hmac.compare_digest(supplied, current_digest)
    previous_match = False
    if secrets.previous is not None:
        previous_digest = hmac.new(secrets.previous, raw_body, hashlib.sha256).hexdigest()
        previous_match = hmac.compare_digest(supplied, previous_digest)
        previous_match = previous_match and _previous_secret_is_active(secrets, aware_now)
    if not current_match and not previous_match:
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_SIGNATURE)
    payload = _strict_object(raw_body)
    action = payload.get("action", "")
    if not isinstance(action, str) or len(action) > 64 or any(ord(character) < 32 for character in action):
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_JSON)
    mutation_allowed = (event, action) in _ALLOWED
    return VerifiedGithubWebhook(
        delivery_id=canonical_delivery_id,
        body_hash=hashlib.sha256(raw_body).hexdigest(),
        event=event,
        action=action,
        github_installation_id=_installation_id(payload) if mutation_allowed else None,
        payload=payload,
        mutation_allowed=mutation_allowed,
        used_previous_secret=previous_match and not current_match,
    )


async def claim_github_webhook(
    webhook: VerifiedGithubWebhook,
    *,
    repository: GithubWebhookDeliveryRepositoryPort,
    now: datetime,
) -> WebhookClaimDecision:
    """Claim a verified delivery for the contract's bounded retention period."""
    aware_now = _aware(now)
    return await repository.claim(
        webhook,
        received_at=aware_now,
        expires_at=aware_now + timedelta(days=WEBHOOK_POLICY_V2.delivery_retention_days),
    )


async def lease_github_webhook_work(
    *,
    repository: GithubWebhookDeliveryRepositoryPort,
    now: datetime,
    lease_token: str,
) -> GithubWebhookWorkLease | None:
    """Lease the oldest due mutation for five minutes."""
    aware_now = _aware(now)
    try:
        canonical_token = str(uuid.UUID(lease_token))
    except (AttributeError, ValueError) as exc:
        raise ValueError("webhook lease token must be a canonical UUID") from exc
    if canonical_token != lease_token:
        raise ValueError("webhook lease token must be a canonical UUID")
    return await repository.lease_next(
        now=aware_now,
        lease_token=canonical_token,
        lease_expires_at=aware_now + _WORK_LEASE,
    )


async def complete_github_webhook_work(
    lease: GithubWebhookWorkLease,
    *,
    repository: GithubWebhookDeliveryRepositoryPort,
    now: datetime,
) -> bool:
    """Complete work only while holding its current lease token."""
    return await repository.complete(lease, processed_at=_aware(now))


async def renew_github_webhook_work(
    lease: GithubWebhookWorkLease,
    *,
    repository: GithubWebhookDeliveryRepositoryPort,
    now: datetime,
) -> bool:
    """Extend an unexpired current lease before applying fetched state."""
    aware_now = _aware(now)
    return await repository.renew(
        lease,
        renewed_at=aware_now,
        lease_expires_at=aware_now + _WORK_LEASE,
    )


async def retry_github_webhook_work(
    lease: GithubWebhookWorkLease,
    *,
    repository: GithubWebhookDeliveryRepositoryPort,
    now: datetime,
    error_code: str,
) -> bool:
    """Release failed work with bounded exponential backoff or terminal failure."""
    aware_now = _aware(now)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_code):
        raise ValueError("webhook work error code is invalid")
    terminal = lease.attempt_count >= _MAXIMUM_WORK_ATTEMPTS
    delay_seconds = min(
        _MAXIMUM_RETRY_SECONDS,
        _INITIAL_RETRY_SECONDS * (2 ** max(0, lease.attempt_count - 1)),
    )
    return await repository.retry(
        lease,
        available_at=aware_now + timedelta(seconds=delay_seconds),
        failed_at=aware_now,
        error_code=error_code,
        terminal=terminal,
    )


def _delivery_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_DELIVERY_ID) from exc
    if str(parsed) != value:
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_DELIVERY_ID)
    return value


def _installation_id(payload: dict[str, Any]) -> int:
    installation = payload.get("installation")
    if not isinstance(installation, dict):
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_JSON)
    value = installation.get("id")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_JSON)
    return value


def _signature_digest(value: str) -> str:
    match = _SIGNATURE.fullmatch(value)
    if match is None:
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_SIGNATURE)
    return match.group(1)


def _previous_secret_is_active(secrets: GithubWebhookSecrets, now: datetime) -> bool:
    valid_until = secrets.previous_valid_until
    if valid_until is None:
        return False
    aware_until = _aware(valid_until)
    maximum_overlap = timedelta(seconds=WEBHOOK_POLICY_V2.secret_overlap_seconds)
    return now <= aware_until <= now + maximum_overlap


def _strict_object(raw_body: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite number")

    try:
        payload = json.loads(raw_body, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_JSON) from exc
    if not isinstance(payload, dict):
        raise GithubWebhookError(GithubWebhookErrorCode.INVALID_JSON)
    return payload


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("webhook timestamps must be timezone-aware")
    return value
