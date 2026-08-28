"""Safety tests for recoverable local-scan SQLite cutover operations."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.modules.atomic.operations.sqlite_cutover import (
    CutoverSafetyError,
    create_verified_backup,
    inspect_database,
    restore_database,
    retention_report,
    verify_backup,
)


NOW = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND_ROOT / "scripts" / "local-cutover.py"


def _database(path: Path, marker: str = "source") -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE alembic_version (version_num TEXT NOT NULL);
            CREATE TABLE marker (value TEXT NOT NULL);
            CREATE TABLE scanner_artifacts (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL);
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                submitting_token_id TEXT
            );
            CREATE TABLE ingest_requests (
                id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                tombstone_expires_at TEXT,
                submitting_token_id TEXT NOT NULL
            );
            CREATE TABLE api_tokens (
                id TEXT PRIMARY KEY,
                revoked_at TEXT,
                expires_at TEXT NOT NULL
            );
            """
        )
        connection.execute("INSERT INTO alembic_version VALUES ('0022_local_ingest_claims')")
        connection.execute("INSERT INTO marker VALUES (?)", (marker,))
        connection.commit()
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(path: Path, target: Path, *, now: datetime = NOW, stopped: bool = True) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "assurance-scan-stopped-writers-v1",
                "target_path": str(target.resolve()),
                "target_sha256": _sha256(target),
                "writers_stopped": stopped,
                "service_state": "stopped" if stopped else "running",
                "observed_at": now.isoformat(),
                "evidence": "docker compose ps reported no API, worker, or retention writers",
            }
        )
    )
    return path


def test_preflight_is_read_only_and_retention_report_counts_without_deleting(tmp_path: Path) -> None:
    database = _database(tmp_path / "preflight.sqlite")
    old = (NOW - timedelta(days=500)).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO scanner_artifacts(created_at) VALUES (?)", (old,))
        connection.execute(
            "INSERT INTO runs(run_id, started_at, completed_at) VALUES ('old-run', ?, ?)",
            (old, old),
        )
        connection.execute(
            "INSERT INTO ingest_requests(state, tombstone_expires_at, submitting_token_id) "
            "VALUES ('tombstoned', ?, 'referenced')",
            (old,),
        )
        connection.execute(
            "INSERT INTO api_tokens(id, expires_at) VALUES ('eligible', ?)", (old,)
        )
        connection.execute(
            "INSERT INTO api_tokens(id, expires_at) VALUES ('referenced', ?)", (old,)
        )
        connection.commit()
    before = _sha256(database)

    report = inspect_database(database)
    retention = retention_report(database, now=NOW)

    assert report.integrity == "ok"
    assert report.foreign_key_violations == 0
    assert report.schema_revision == "0022_local_ingest_claims"
    assert retention.raw_artifacts == 1
    assert retention.normalized_runs == 1
    assert retention.expired_tombstones == 1
    assert retention.token_audits == 1
    assert _sha256(database) == before


def test_backup_is_verified_content_addressed_and_owner_read_only(tmp_path: Path) -> None:
    database = _database(tmp_path / "source.sqlite")
    backup = tmp_path / "backups" / "cutover.sqlite"
    manifest_path = tmp_path / "backups" / "cutover.json"
    backup.parent.mkdir()

    manifest = create_verified_backup(
        database,
        backup,
        manifest_path,
        application_revision="git:abc123",
        now=NOW,
    )

    assert manifest == verify_backup(backup, manifest_path)
    assert manifest.backup_sha256 == _sha256(backup)
    assert manifest.source_schema_revision == "0022_local_ingest_claims"
    assert stat.S_IMODE(backup.stat().st_mode) == stat.S_IRUSR
    assert stat.S_IMODE(manifest_path.stat().st_mode) == stat.S_IRUSR
    with pytest.raises(CutoverSafetyError, match="must not already exist"):
        create_verified_backup(
            database,
            backup,
            manifest_path,
            application_revision="git:abc123",
        )


def test_verify_backup_rejects_corruption(tmp_path: Path) -> None:
    database = _database(tmp_path / "source.sqlite")
    backup = tmp_path / "backup.sqlite"
    manifest_path = tmp_path / "backup.json"
    create_verified_backup(database, backup, manifest_path, application_revision="release-1")
    os.chmod(backup, stat.S_IRUSR | stat.S_IWUSR)
    with backup.open("ab") as handle:
        handle.write(b"tamper")

    with pytest.raises(CutoverSafetyError, match="digest or size"):
        verify_backup(backup, manifest_path)


def test_restore_requires_exact_fresh_stopped_writer_evidence_and_confirmation(
    tmp_path: Path,
) -> None:
    source = _database(tmp_path / "source.sqlite", marker="backup")
    target = _database(tmp_path / "target.sqlite", marker="current")
    backup = tmp_path / "backup.sqlite"
    manifest_path = tmp_path / "backup.json"
    manifest = create_verified_backup(source, backup, manifest_path, application_revision="release-1")
    evidence = _evidence(tmp_path / "writers.json", target)
    confirmation = f"RESTORE {manifest.backup_sha256} TO {target.resolve()}"

    with pytest.raises(CutoverSafetyError, match="confirmation must exactly equal"):
        restore_database(
            backup,
            manifest_path,
            target,
            evidence,
            confirmation="RESTORE yes",
            execute=False,
            now=NOW,
        )
    running_evidence = _evidence(tmp_path / "running.json", target, stopped=False)
    with pytest.raises(CutoverSafetyError, match="does not prove stopped services"):
        restore_database(
            backup,
            manifest_path,
            target,
            running_evidence,
            confirmation=confirmation,
            execute=False,
            now=NOW,
        )
    plan = restore_database(
        backup,
        manifest_path,
        target,
        evidence,
        confirmation=confirmation,
        execute=False,
        now=NOW,
    )
    assert isinstance(plan, dict) and plan["status"] == "verified-dry-run"

    stale_evidence = _evidence(
        tmp_path / "stale.json", target, now=NOW - timedelta(minutes=16)
    )
    with pytest.raises(CutoverSafetyError, match="stale"):
        restore_database(
            backup,
            manifest_path,
            target,
            stale_evidence,
            confirmation=confirmation,
            execute=False,
            now=NOW,
        )
    Path(f"{target}-wal").write_bytes(b"active writer evidence")
    with pytest.raises(CutoverSafetyError, match="sidecar"):
        restore_database(
            backup,
            manifest_path,
            target,
            evidence,
            confirmation=confirmation,
            execute=False,
            now=NOW,
        )


def test_guarded_restore_preserves_recovery_copy_and_verifies_result(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.sqlite", marker="backup")
    target = _database(tmp_path / "target.sqlite", marker="current")
    backup = tmp_path / "backup.sqlite"
    manifest_path = tmp_path / "backup.json"
    manifest = create_verified_backup(source, backup, manifest_path, application_revision="release-1")
    evidence = _evidence(tmp_path / "writers.json", target)
    current_digest = _sha256(target)

    result = restore_database(
        backup,
        manifest_path,
        target,
        evidence,
        confirmation=f"RESTORE {manifest.backup_sha256} TO {target.resolve()}",
        execute=True,
        now=NOW,
    )

    assert not isinstance(result, dict)
    assert result.restored_sha256 == manifest.backup_sha256
    assert result.recovery_sha256 == current_digest
    assert _sha256(Path(result.recovery_path)) == current_digest
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("backup",)


def test_operator_cli_emits_machine_readable_read_only_preflight(tmp_path: Path) -> None:
    database = _database(tmp_path / "cli.sqlite")
    before = _sha256(database)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "preflight", "--database", str(database)],
        cwd=BACKEND_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert payload["database"]["integrity"] == "ok"
    assert payload["retention_dry_run"]["raw_artifacts"] == 0
    assert _sha256(database) == before
