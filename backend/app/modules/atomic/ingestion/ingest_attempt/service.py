"""Validate and minimize durable ingest-attempt evidence."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

from app.modules.shared.contracts.ingest_v2 import (
    INGEST_ATTEMPT_OUTCOMES,
    INGEST_REASON_CODES,
)

from .models import IngestAttemptCommand, IngestAttemptRecord


RETENTION = timedelta(days=30)
ORIGINS = frozenset(("github", "local"))
PRINCIPAL_KINDS = frozenset(("github_oidc", "local_token"))


def build_ingest_attempt(command: IngestAttemptCommand) -> IngestAttemptRecord:
    """Return a constrained record containing hashes, never raw identities."""
    correlation = _canonical_uuid(command.correlation_id, "correlation ID")
    if command.origin not in ORIGINS or command.principal_kind not in PRINCIPAL_KINDS:
        raise ValueError("ingest attempt origin or principal kind is invalid")
    if command.outcome not in INGEST_ATTEMPT_OUTCOMES:
        raise ValueError("ingest attempt outcome is invalid")
    if command.reason_code not in INGEST_REASON_CODES:
        raise ValueError("ingest attempt reason code is invalid")
    if command.project_id <= 0 or not command.principal_reference or not command.canonical_request_key:
        raise ValueError("ingest attempt binding fields are required")
    if command.submitted_by_user_id is not None and command.submitted_by_user_id <= 0:
        raise ValueError("submitting user ID must be positive")
    if not isinstance(command.wire_bytes, int) or isinstance(command.wire_bytes, bool) or command.wire_bytes < 0:
        raise ValueError("ingest attempt wire bytes must be a non-negative integer")
    if command.received_at.tzinfo is None or command.completed_at.tzinfo is None:
        raise ValueError("ingest attempt timestamps must be timezone-aware")
    if command.completed_at < command.received_at:
        raise ValueError("ingest attempt completion precedes receipt")
    return IngestAttemptRecord(
        id=str(uuid.uuid4()),
        correlation_id=correlation,
        origin=command.origin,
        project_id=command.project_id,
        principal_kind=command.principal_kind,
        principal_reference_hash=_sha256(command.principal_reference),
        canonical_request_key_hash=_sha256(command.canonical_request_key),
        outcome=command.outcome,
        reason_code=command.reason_code,
        retryable=command.retryable,
        wire_bytes=command.wire_bytes,
        received_at=command.received_at,
        completed_at=command.completed_at,
        expires_at=command.received_at + RETENTION,
        run_id=command.run_id,
        submitted_by_user_id=command.submitted_by_user_id,
    )


def _canonical_uuid(value: str, label: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{label} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise ValueError(f"{label} must be a canonical UUID")
    return value


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["RETENTION", "build_ingest_attempt"]
