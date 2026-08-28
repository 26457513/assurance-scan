"""Conservative, recoverable SQLite backup and restore operations."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from app.modules.shared.contracts.local_scan import RETENTION_DAYS

from .models import BackupManifest, DatabaseReport, RestoreResult, RetentionReport


MANIFEST_SCHEMA = "assurance-scan-sqlite-backup-v1"
STOPPED_WRITERS_SCHEMA = "assurance-scan-stopped-writers-v1"
_MAX_EVIDENCE_AGE = dt.timedelta(minutes=15)
_REPORT_TABLES = (
    "alembic_version",
    "projects",
    "runs",
    "scanner_artifacts",
    "ingest_requests",
    "api_tokens",
)


class CutoverSafetyError(RuntimeError):
    """An operator guard or verification check failed."""


def inspect_database(database: Path) -> DatabaseReport:
    """Inspect an existing database through a strictly read-only connection."""
    path = _existing_regular_file(database, label="database")
    with _readonly_connection(path) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        counts = {
            table: int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
            for table in _REPORT_TABLES
            if table in tables
        }
        revision = _schema_revision(connection, tables)
    return DatabaseReport(
        path=str(path),
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        integrity=integrity,
        foreign_key_violations=violations,
        schema_revision=revision,
        table_counts=counts,
        wal_present=_sidecar(path, "-wal").exists(),
        shm_present=_sidecar(path, "-shm").exists(),
    )


def create_verified_backup(
    source: Path,
    backup: Path,
    manifest_path: Path,
    *,
    application_revision: str,
    now: dt.datetime | None = None,
) -> BackupManifest:
    """Create an online SQLite backup, verify it, then publish it atomically."""
    source_path = _existing_regular_file(source, label="source database")
    backup_path = _new_explicit_path(backup, label="backup")
    metadata_path = _new_explicit_path(manifest_path, label="backup manifest")
    if backup_path == source_path or metadata_path in {source_path, backup_path}:
        raise CutoverSafetyError("source, backup, and manifest paths must be distinct")
    if not application_revision.strip():
        raise CutoverSafetyError("application revision is required")
    timestamp = _aware_now(now)
    source_report = inspect_database(source_path)
    if source_report.integrity != "ok" or source_report.foreign_key_violations:
        raise CutoverSafetyError("source database failed integrity verification")

    temporary = _temporary_path(backup_path.parent, prefix=f".{backup_path.name}.")
    try:
        with _readonly_connection(source_path) as source_connection, sqlite3.connect(
            temporary
        ) as destination_connection:
            source_connection.backup(destination_connection)
        backup_report = inspect_database(temporary)
        if backup_report.integrity != "ok" or backup_report.foreign_key_violations:
            raise CutoverSafetyError("new backup failed integrity verification")
        manifest = BackupManifest(
            schema=MANIFEST_SCHEMA,
            backup_path=str(backup_path),
            backup_sha256=backup_report.sha256,
            size_bytes=backup_report.size_bytes,
            created_at=timestamp.isoformat(),
            source_path=str(source_path),
            source_schema_revision=source_report.schema_revision,
            application_revision=application_revision.strip(),
            integrity=backup_report.integrity,
            foreign_key_violations=backup_report.foreign_key_violations,
        )
        os.chmod(temporary, stat.S_IRUSR)
        os.replace(temporary, backup_path)
        _write_manifest(metadata_path, manifest)
        _fsync_directory(backup_path.parent)
        return verify_backup(backup_path, metadata_path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_backup(backup: Path, manifest_path: Path) -> BackupManifest:
    """Verify manifest binding, digest, size, integrity, and foreign keys."""
    backup_path = _existing_regular_file(backup, label="backup")
    metadata_path = _existing_regular_file(manifest_path, label="backup manifest")
    try:
        data = cast(dict[str, Any], json.loads(metadata_path.read_text(encoding="utf-8")))
        manifest = BackupManifest(**data)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CutoverSafetyError("backup manifest is invalid") from exc
    if manifest.schema != MANIFEST_SCHEMA:
        raise CutoverSafetyError("backup manifest schema is unsupported")
    if Path(manifest.backup_path) != backup_path:
        raise CutoverSafetyError("backup path does not match its manifest")
    report = inspect_database(backup_path)
    if report.sha256 != manifest.backup_sha256 or report.size_bytes != manifest.size_bytes:
        raise CutoverSafetyError("backup digest or size does not match its manifest")
    if report.integrity != "ok" or report.foreign_key_violations:
        raise CutoverSafetyError("backup database failed integrity verification")
    return manifest


def retention_report(database: Path, *, now: dt.datetime | None = None) -> RetentionReport:
    """Count rows eligible for retention without mutating the database."""
    path = _existing_regular_file(database, label="database")
    timestamp = _aware_now(now)
    raw_cutoff = timestamp - dt.timedelta(days=RETENTION_DAYS.raw_artifacts)
    run_cutoff = timestamp - dt.timedelta(days=RETENTION_DAYS.normalized_history)
    audit_cutoff = timestamp - dt.timedelta(days=RETENTION_DAYS.token_audit_after_inactive)
    with _readonly_connection(path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        raw = _count_if(
            connection,
            tables,
            "scanner_artifacts",
            "created_at <= ?",
            (raw_cutoff.isoformat(),),
        )
        runs = _count_if(
            connection,
            tables,
            "runs",
            "(completed_at <= ?) OR (completed_at IS NULL AND started_at <= ?)",
            (run_cutoff.isoformat(), run_cutoff.isoformat()),
        )
        tombstones = _count_if(
            connection,
            tables,
            "ingest_requests",
            "state = 'tombstoned' AND tombstone_expires_at <= ?",
            (timestamp.isoformat(),),
        )
        token_audits = _eligible_token_audits(connection, tables, audit_cutoff)
    return RetentionReport(timestamp.isoformat(), raw, runs, tombstones, token_audits)


def restore_database(
    backup: Path,
    manifest_path: Path,
    target: Path,
    stopped_writer_evidence: Path,
    *,
    confirmation: str,
    execute: bool,
    now: dt.datetime | None = None,
) -> RestoreResult | dict[str, str]:
    """Verify a guarded restore plan and optionally perform a recoverable swap."""
    manifest = verify_backup(backup, manifest_path)
    target_path = _existing_regular_file(target, label="restore target")
    timestamp = _aware_now(now)
    target_digest = _sha256(target_path)
    evidence = _verify_stopped_writer_evidence(
        stopped_writer_evidence, target_path, target_digest, timestamp
    )
    del evidence
    expected_confirmation = f"RESTORE {manifest.backup_sha256} TO {target_path}"
    if confirmation != expected_confirmation:
        raise CutoverSafetyError(f"confirmation must exactly equal: {expected_confirmation}")
    for suffix in ("-wal", "-shm"):
        sidecar = _sidecar(target_path, suffix)
        if sidecar.exists():
            raise CutoverSafetyError(f"restore target has SQLite sidecar {sidecar.name}; checkpoint it first")
    recovery = target_path.with_name(
        f"{target_path.name}.pre-restore-{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{target_digest[:8]}"
    )
    if recovery.exists():
        raise CutoverSafetyError("recovery path already exists")
    if not execute:
        return {
            "status": "verified-dry-run",
            "backup_sha256": manifest.backup_sha256,
            "target_sha256": target_digest,
            "recovery_path": str(recovery),
        }

    replacement = _temporary_path(target_path.parent, prefix=f".{target_path.name}.restore.")
    target_mode = stat.S_IMODE(target_path.stat().st_mode)
    moved_original = False
    try:
        _copy_verified_backup(Path(manifest.backup_path), replacement)
        os.chmod(replacement, target_mode)
        if _sha256(target_path) != target_digest:
            raise CutoverSafetyError("restore target changed while the restore was being staged")
        if any(_sidecar(target_path, suffix).exists() for suffix in ("-wal", "-shm")):
            raise CutoverSafetyError("SQLite sidecar appeared while the restore was being staged")
        os.replace(target_path, recovery)
        moved_original = True
        os.replace(replacement, target_path)
        _fsync_directory(target_path.parent)
        restored = inspect_database(target_path)
        if restored.sha256 != manifest.backup_sha256 or restored.integrity != "ok":
            raise CutoverSafetyError("restored target failed post-swap verification")
        return RestoreResult(str(target_path), restored.sha256, str(recovery), target_digest)
    except Exception:
        if moved_original and recovery.exists():
            failed = target_path.with_name(f".{target_path.name}.failed-restore")
            if target_path.exists() and not failed.exists():
                os.replace(target_path, failed)
            os.replace(recovery, target_path)
            _fsync_directory(target_path.parent)
        raise
    finally:
        replacement.unlink(missing_ok=True)


def _verify_stopped_writer_evidence(
    evidence_path: Path,
    target: Path,
    target_digest: str,
    now: dt.datetime,
) -> dict[str, Any]:
    path = _existing_regular_file(evidence_path, label="stopped-writer evidence")
    try:
        evidence = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        observed = dt.datetime.fromisoformat(str(evidence["observed_at"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CutoverSafetyError("stopped-writer evidence is invalid") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise CutoverSafetyError("stopped-writer evidence timestamp must be timezone-aware")
    if evidence.get("schema") != STOPPED_WRITERS_SCHEMA:
        raise CutoverSafetyError("stopped-writer evidence schema is unsupported")
    if evidence.get("writers_stopped") is not True or evidence.get("service_state") != "stopped":
        raise CutoverSafetyError("stopped-writer evidence does not prove stopped services")
    if not str(evidence.get("evidence", "")).strip():
        raise CutoverSafetyError("stopped-writer evidence must describe the operator check")
    if Path(str(evidence.get("target_path", ""))).resolve() != target:
        raise CutoverSafetyError("stopped-writer evidence names a different target")
    if evidence.get("target_sha256") != target_digest:
        raise CutoverSafetyError("restore target changed after stopped-writer evidence was recorded")
    age = now - observed.astimezone(dt.timezone.utc)
    if age < -dt.timedelta(minutes=1) or age > _MAX_EVIDENCE_AGE:
        raise CutoverSafetyError("stopped-writer evidence is stale or from the future")
    return evidence


def _copy_verified_backup(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)
    report = inspect_database(destination)
    if report.sha256 != _sha256(source) or report.integrity != "ok" or report.foreign_key_violations:
        raise CutoverSafetyError("restore staging database failed verification")


def _write_manifest(path: Path, manifest: BackupManifest) -> None:
    temporary = _temporary_path(path.parent, prefix=f".{path.name}.")
    try:
        temporary.write_text(
            json.dumps(dataclasses.asdict(manifest), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, stat.S_IRUSR)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _eligible_token_audits(
    connection: sqlite3.Connection, tables: set[str], cutoff: dt.datetime
) -> int:
    required = {"api_tokens", "runs", "ingest_requests"}
    if not required.issubset(tables):
        return 0
    if not {"id", "revoked_at", "expires_at"}.issubset(_columns(connection, "api_tokens")):
        return 0
    if "submitting_token_id" not in _columns(connection, "runs"):
        return 0
    if "submitting_token_id" not in _columns(connection, "ingest_requests"):
        return 0
    row = connection.execute(
        "SELECT count(*) FROM api_tokens t "
        "WHERE (t.revoked_at <= ? OR t.expires_at <= ?) "
        "AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.submitting_token_id = t.id) "
        "AND NOT EXISTS (SELECT 1 FROM ingest_requests i WHERE i.submitting_token_id = t.id)",
        (cutoff.isoformat(), cutoff.isoformat()),
    ).fetchone()
    return int(row[0])


def _count_if(
    connection: sqlite3.Connection,
    tables: set[str],
    table: str,
    predicate: str,
    parameters: tuple[str, ...],
) -> int:
    if table not in tables:
        return 0
    required_columns = {
        "scanner_artifacts": {"created_at"},
        "runs": {"started_at", "completed_at"},
        "ingest_requests": {"state", "tombstone_expires_at"},
    }.get(table, set())
    if not required_columns.issubset(_columns(connection, table)):
        return 0
    row = connection.execute(f'SELECT count(*) FROM "{table}" WHERE {predicate}', parameters).fetchone()
    return int(row[0])


def _schema_revision(connection: sqlite3.Connection, tables: set[str]) -> str | None:
    if "alembic_version" not in tables:
        return None
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return str(row[0]) if row else None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _existing_regular_file(path: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise CutoverSafetyError(f"{label} must be an existing non-symlink regular file")
    return resolved


def _new_explicit_path(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise CutoverSafetyError(f"{label} path must be absolute")
    if expanded.is_symlink() or expanded.exists():
        raise CutoverSafetyError(f"{label} path must not already exist")
    parent = expanded.parent.resolve(strict=True)
    if not parent.is_dir():
        raise CutoverSafetyError(f"{label} parent must be a directory")
    return parent / expanded.name


def _temporary_path(parent: Path, *, prefix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, dir=parent)
    os.close(descriptor)
    return Path(name)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecar(path: Path, suffix: str) -> Path:
    return Path(f"{path}{suffix}")


def _aware_now(value: dt.datetime | None) -> dt.datetime:
    timestamp = value or dt.datetime.now(dt.timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise CutoverSafetyError("operation timestamp must be timezone-aware")
    return timestamp.astimezone(dt.timezone.utc)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "CutoverSafetyError",
    "create_verified_backup",
    "inspect_database",
    "restore_database",
    "retention_report",
    "verify_backup",
]
