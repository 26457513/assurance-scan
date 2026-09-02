"""Application-neutral orchestration for leased idempotency claims."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from .models import (
    ClaimCommand,
    ClaimResult,
    GithubClaimCommand,
    GithubIdempotencyClaim,
    IdempotencyClaim,
    IdempotencyValidationError,
)
from .ports import GithubIdempotencyRepositoryPort, IdempotencyRepositoryPort


DEFAULT_LEASE = timedelta(minutes=5)
DEFAULT_TOMBSTONE_RETENTION = timedelta(days=30)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_claim_command(command: ClaimCommand) -> ClaimCommand:
    """Reject non-canonical keys before they reach durable storage."""
    if command.user_id <= 0 or command.project_id <= 0 or not command.token_id:
        raise IdempotencyValidationError("user_id and project_id must be positive")
    try:
        request_id = uuid.UUID(command.client_request_id)
    except (ValueError, AttributeError) as exc:
        raise IdempotencyValidationError("client request id must be a canonical UUIDv4") from exc
    if request_id.version != 4 or str(request_id) != command.client_request_id:
        raise IdempotencyValidationError("client request id must be a canonical lowercase UUIDv4")
    _validate_content(command.payload_hash, command.accepted_bytes)
    return command


def validate_github_claim_command(command: GithubClaimCommand) -> GithubClaimCommand:
    """Reject non-canonical GitHub identities before durable storage."""
    identifiers = (
        command.github_repository_id,
        command.github_owner_id,
        command.github_run_id,
        command.run_attempt,
        command.project_id,
    )
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in identifiers):
        raise IdempotencyValidationError("GitHub repository, run, attempt and project IDs must be positive integers")
    _validate_content(command.payload_hash, command.accepted_bytes)
    return command


async def acquire_claim(
    command: ClaimCommand,
    *,
    repository: IdempotencyRepositoryPort,
    now: datetime,
    lease_duration: timedelta = DEFAULT_LEASE,
) -> ClaimResult:
    """Acquire, replay, reject, or safely take over a durable claim."""
    validate_claim_command(command)
    aware_now = _aware(now)
    if lease_duration <= timedelta(0):
        raise IdempotencyValidationError("lease duration must be positive")
    return await repository.acquire(
        command,
        now=aware_now,
        lease_expires_at=aware_now + lease_duration,
    )


async def acquire_github_claim(
    command: GithubClaimCommand,
    *,
    repository: GithubIdempotencyRepositoryPort,
    now: datetime,
    lease_duration: timedelta = DEFAULT_LEASE,
) -> ClaimResult:
    """Acquire, replay, reject, or take over one GitHub run-attempt claim."""
    validate_github_claim_command(command)
    aware_now = _aware(now)
    if lease_duration <= timedelta(0):
        raise IdempotencyValidationError("lease duration must be positive")
    return await repository.acquire(
        command,
        now=aware_now,
        lease_expires_at=aware_now + lease_duration,
    )


def claim_handle(command: ClaimCommand, result: ClaimResult) -> IdempotencyClaim:
    """Create a CAS lease handle only for a successful acquisition."""
    if not result.acquired or result.lease_expires_at is None or result.lease_id is None:
        raise IdempotencyValidationError("only an acquired result has a lease handle")
    return IdempotencyClaim(
        user_id=command.user_id,
        client_request_id=command.client_request_id,
        payload_hash=command.payload_hash,
        lease_id=result.lease_id,
        lease_expires_at=result.lease_expires_at,
    )


def github_claim_handle(
    command: GithubClaimCommand,
    result: ClaimResult,
) -> GithubIdempotencyClaim:
    """Create a fenced handle only after a successful GitHub acquisition."""
    if not result.acquired or result.lease_expires_at is None or result.lease_id is None:
        raise IdempotencyValidationError("only an acquired result has a lease handle")
    return GithubIdempotencyClaim(
        github_repository_id=command.github_repository_id,
        github_owner_id=command.github_owner_id,
        github_run_id=command.github_run_id,
        run_attempt=command.run_attempt,
        payload_hash=command.payload_hash,
        lease_id=result.lease_id,
        lease_expires_at=result.lease_expires_at,
    )


async def heartbeat_claim(
    claim: IdempotencyClaim,
    *,
    repository: IdempotencyRepositoryPort,
    now: datetime,
    lease_duration: timedelta = DEFAULT_LEASE,
) -> IdempotencyClaim | None:
    """Extend a still-owned lease using its previous expiry as a CAS token."""
    aware_now = _aware(now)
    if lease_duration <= timedelta(0):
        raise IdempotencyValidationError("lease duration must be positive")
    new_expiry = aware_now + lease_duration
    if not await repository.heartbeat(claim, new_lease_expires_at=new_expiry):
        return None
    return IdempotencyClaim(
        user_id=claim.user_id,
        client_request_id=claim.client_request_id,
        payload_hash=claim.payload_hash,
        lease_id=claim.lease_id,
        lease_expires_at=new_expiry,
    )


async def tombstone_completed_claim(
    run_id: str,
    *,
    repository: IdempotencyRepositoryPort,
    now: datetime,
    retention: timedelta = DEFAULT_TOMBSTONE_RETENTION,
) -> bool:
    """Detach a completed claim before its run is deleted."""
    aware_now = _aware(now)
    if not run_id or retention <= timedelta(0):
        raise IdempotencyValidationError("run id and positive tombstone retention are required")
    return await repository.tombstone_completed(
        run_id=run_id,
        now=aware_now,
        expires_at=aware_now + retention,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IdempotencyValidationError("idempotency timestamps must be timezone-aware")
    return value


def _validate_content(payload_hash: str, accepted_bytes: int) -> None:
    if not isinstance(accepted_bytes, int) or isinstance(accepted_bytes, bool) or accepted_bytes < 0:
        raise IdempotencyValidationError("accepted bytes must be a non-negative integer")
    if _SHA256.fullmatch(payload_hash) is None:
        raise IdempotencyValidationError("payload hash must be lowercase SHA-256 hex")


__all__ = [
    "DEFAULT_LEASE",
    "DEFAULT_TOMBSTONE_RETENTION",
    "acquire_claim",
    "acquire_github_claim",
    "claim_handle",
    "github_claim_handle",
    "heartbeat_claim",
    "tombstone_completed_claim",
    "validate_claim_command",
    "validate_github_claim_command",
]
