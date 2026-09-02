"""Framework-free safe ingest-attempt audit records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IngestAttemptCommand:
    correlation_id: str
    origin: str
    project_id: int
    principal_kind: str
    principal_reference: str
    canonical_request_key: str
    outcome: str
    reason_code: str
    retryable: bool
    wire_bytes: int
    received_at: datetime
    completed_at: datetime
    run_id: str | None = None
    submitted_by_user_id: int | None = None


@dataclass(frozen=True)
class IngestAttemptRecord:
    id: str
    correlation_id: str
    origin: str
    project_id: int
    principal_kind: str
    principal_reference_hash: str
    canonical_request_key_hash: str
    outcome: str
    reason_code: str
    retryable: bool
    wire_bytes: int
    received_at: datetime
    completed_at: datetime
    expires_at: datetime
    run_id: str | None = None
    submitted_by_user_id: int | None = None


__all__ = ["IngestAttemptCommand", "IngestAttemptRecord"]
