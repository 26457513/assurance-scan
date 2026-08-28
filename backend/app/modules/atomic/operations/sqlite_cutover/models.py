"""Serializable contracts for SQLite cutover operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseReport:
    path: str
    sha256: str
    size_bytes: int
    integrity: str
    foreign_key_violations: int
    schema_revision: str | None
    table_counts: dict[str, int]
    wal_present: bool
    shm_present: bool


@dataclass(frozen=True)
class BackupManifest:
    schema: str
    backup_path: str
    backup_sha256: str
    size_bytes: int
    created_at: str
    source_path: str
    source_schema_revision: str | None
    application_revision: str
    integrity: str
    foreign_key_violations: int


@dataclass(frozen=True)
class RetentionReport:
    as_of: str
    raw_artifacts: int
    normalized_runs: int
    expired_tombstones: int
    token_audits: int


@dataclass(frozen=True)
class RestoreResult:
    target_path: str
    restored_sha256: str
    recovery_path: str
    recovery_sha256: str


__all__ = ["BackupManifest", "DatabaseReport", "RestoreResult", "RetentionReport"]
