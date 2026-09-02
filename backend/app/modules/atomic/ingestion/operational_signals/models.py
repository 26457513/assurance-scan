"""Secret-free operational signal contracts for local ingest."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalIngestRequestSignal:
    """Bounded request telemetry containing no user-controlled text."""

    outcome: str
    status_code: int
    duration_ms: int
    code: str
    wire_bytes: int | None = None
    finding_count: int | None = None
    scanner_count: int | None = None
    redaction_count: int | None = None
    project_id: int | None = None
    replayed: bool | None = None


@dataclass(frozen=True)
class LocalIngestRetentionSignal:
    """Counts emitted after one retention-cleanup pass."""

    outcome: str
    duration_ms: int
    raw_artifacts: int = 0
    normalized_runs: int = 0
    token_audits: int = 0
    tombstones: int = 0
    webhook_deliveries: int = 0


__all__ = ["LocalIngestRequestSignal", "LocalIngestRetentionSignal"]
