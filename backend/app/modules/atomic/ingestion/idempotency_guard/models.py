"""Framework-free contracts for durable local-ingest idempotency."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ClaimDecision(StrEnum):
    """Exhaustive outcomes of an atomic idempotency-key claim."""

    ACQUIRED = "acquired"
    STALE_TAKEOVER = "stale_takeover"
    REPLAY = "replay"
    CONFLICT = "conflict"
    IN_PROGRESS = "in_progress"
    TOMBSTONED = "tombstoned"


@dataclass(frozen=True)
class ClaimCommand:
    """Validated identity and content bound to one upload attempt."""

    user_id: int
    token_id: str
    client_request_id: str
    project_id: int
    payload_hash: str
    accepted_bytes: int


@dataclass(frozen=True)
class ClaimResult:
    """Result returned by the durable claim repository."""

    decision: ClaimDecision
    lease_id: str | None = None
    lease_expires_at: datetime | None = None
    run_id: str | None = None

    @property
    def acquired(self) -> bool:
        return self.decision in {ClaimDecision.ACQUIRED, ClaimDecision.STALE_TAKEOVER}


@dataclass(frozen=True)
class IdempotencyClaim:
    """Lease handle used for compare-and-swap lifecycle operations."""

    user_id: int
    client_request_id: str
    payload_hash: str
    lease_id: str
    lease_expires_at: datetime


@dataclass(frozen=True)
class GithubClaimCommand:
    """Authoritative GitHub run identity and content for one upload."""

    github_repository_id: int
    github_owner_id: int
    github_run_id: int
    run_attempt: int
    project_id: int
    payload_hash: str
    accepted_bytes: int


@dataclass(frozen=True)
class GithubIdempotencyClaim:
    """Fenced lease handle for one GitHub run attempt."""

    github_repository_id: int
    github_owner_id: int
    github_run_id: int
    run_attempt: int
    payload_hash: str
    lease_id: str
    lease_expires_at: datetime


class IdempotencyValidationError(ValueError):
    """A request identifier, hash, or lease duration is not canonical."""


__all__ = [
    "ClaimCommand",
    "ClaimDecision",
    "ClaimResult",
    "GithubClaimCommand",
    "GithubIdempotencyClaim",
    "IdempotencyClaim",
    "IdempotencyValidationError",
]
