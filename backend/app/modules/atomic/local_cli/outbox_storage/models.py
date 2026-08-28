"""Contracts for persistent owner-only upload retry records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class OutboxState(StrEnum):
    PENDING = "pending"
    RETRYABLE = "retryable"
    PERMANENT_REJECTION = "permanent_rejection"
    UPLOADED = "uploaded"


@dataclass(frozen=True)
class OutboxRecord:
    request_id: str
    state: OutboxState
    created_at: datetime
    updated_at: datetime
    total_bytes: int
    last_error_code: str | None = None
    run_url: str | None = None


@dataclass(frozen=True)
class OutboxEntry:
    record: OutboxRecord
    path: Path
    artifact_names: tuple[str, ...]


@dataclass(frozen=True)
class PruneResult:
    removed_request_ids: tuple[str, ...]
    skipped_locked_request_ids: tuple[str, ...]
    retained_bytes: int


class OutboxStorageError(RuntimeError):
    """Outbox content or its filesystem boundary is unsafe."""


class OutboxLockedError(OutboxStorageError):
    """The request is actively owned by another process."""


__all__ = [
    "OutboxEntry",
    "OutboxLockedError",
    "OutboxRecord",
    "OutboxState",
    "OutboxStorageError",
    "PruneResult",
]
