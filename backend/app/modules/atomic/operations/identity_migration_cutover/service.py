"""Restart-safe, checksum-bound SQLite identity cutover operations."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sqlite3
import stat
import time
from pathlib import Path
from typing import Callable

from app.modules.atomic.operations.identity_migration_preflight import (
    inspect_identity_migration,
)

from .models import IdentityCutoverError, IdentityCutoverResult


MIGRATION_REVISION = "0028_identity_cutover_journal"
SUPPORTED_SCHEMA_REVISIONS = frozenset(
    (
        MIGRATION_REVISION,
        "0029_github_app_access_plane",
        "0030_github_webhook_work_queue",
        "0031_github_app_entitlement_freshness",
        "0032_github_oidc_replays",
        "0033_github_run_attempt_identity",
        "0034_github_ingest_claims",
        "0035_github_ingest_quotas_attempts",
        "0036_ingest_usage_ledger",
    )
)
PHASES = (
    "preflight_verified",
    "dispositions_applied",
    "run_ids_migrated",
    "validated",
    "switch_complete",
)
_RUN_CHILD_TABLES = (
    "scan_jobs",
    "ingest_requests",
    "scanner_runs",
    "findings",
    "source_contexts",
    "test_results",
    "evidence",
    "fr_state",
)
_HEADROOM_BYTES = 2 * 1024 * 1024 * 1024


def run_identity_cutover(
    database: Path,
    *,
    expected_preflight_checksum: str,
    cutover_at: dt.datetime,
    confirm_switch: bool,
) -> IdentityCutoverResult:
    """Apply or resume all cutover phases, stopping before switch unless confirmed."""
    started_at = time.monotonic()
    path = _validated_database(database)
    timestamp = _utc_timestamp(cutover_at)
    if len(expected_preflight_checksum) != 64 or any(
        character not in "0123456789abcdef" for character in expected_preflight_checksum
    ):
        raise IdentityCutoverError("expected preflight checksum must be 64 lowercase hex characters")
    database_bytes = path.stat().st_size
    available = shutil.disk_usage(path.parent).free
    required = database_bytes * 2 + _HEADROOM_BYTES

    with sqlite3.connect(path, timeout=30) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        _require_cutover_schema(connection)
        completed = _completed_phases(connection, expected_preflight_checksum)

    if "preflight_verified" not in completed:
        if available < required:
            raise IdentityCutoverError("insufficient free space for identity cutover")
        preflight = inspect_identity_migration(path)
        if preflight.blocked:
            raise IdentityCutoverError("identity preflight is blocked")
        if preflight.schema_revision not in SUPPORTED_SCHEMA_REVISIONS:
            raise IdentityCutoverError("database is not at the identity cutover revision")
        if preflight.checksum != expected_preflight_checksum:
            raise IdentityCutoverError("identity preflight checksum does not match")
        _run_phase(path, "preflight_verified", expected_preflight_checksum, timestamp, lambda _db: None)

    _run_phase(path, "dispositions_applied", expected_preflight_checksum, timestamp, _apply_dispositions)
    _run_phase(path, "run_ids_migrated", expected_preflight_checksum, timestamp, _migrate_run_ids)
    _run_phase(
        path,
        "validated",
        expected_preflight_checksum,
        timestamp,
        lambda connection: _validate_cutover(connection, timestamp),
    )
    if confirm_switch:
        _run_phase(
            path,
            "switch_complete",
            expected_preflight_checksum,
            timestamp,
            lambda connection: _validate_cutover(connection, timestamp),
        )

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        phases = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT phase FROM identity_migration_journal ORDER BY CASE phase "
                "WHEN 'preflight_verified' THEN 1 WHEN 'dispositions_applied' THEN 2 "
                "WHEN 'run_ids_migrated' THEN 3 WHEN 'validated' THEN 4 "
                "WHEN 'switch_complete' THEN 5 END"
            )
        )
        counts, checksum = _state(connection)
    return IdentityCutoverResult(
        status="switch_complete" if "switch_complete" in phases else "validated",
        preflight_checksum=expected_preflight_checksum,
        state_checksum=checksum,
        completed_phases=phases,
        counts=counts,
        database_bytes=database_bytes,
        required_free_bytes=required,
        available_free_bytes=available,
        duration_ms=round((time.monotonic() - started_at) * 1000),
    )


def _run_phase(
    path: Path,
    phase: str,
    preflight_checksum: str,
    completed_at: str,
    operation: Callable[[sqlite3.Connection], None],
) -> None:
    with sqlite3.connect(path, timeout=30, isolation_level=None) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT preflight_checksum FROM identity_migration_journal WHERE phase=?",
            (phase,),
        ).fetchone()
        if existing is not None:
            if str(existing[0]) != preflight_checksum:
                connection.rollback()
                raise IdentityCutoverError("migration journal checksum mismatch")
            connection.rollback()
            return
        try:
            operation(connection)
            counts, state_checksum = _state(connection)
            connection.execute(
                "INSERT INTO identity_migration_journal "
                "(phase, preflight_checksum, state_checksum, counts_json, completed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    phase,
                    preflight_checksum,
                    state_checksum,
                    json.dumps(counts, sort_keys=True, separators=(",", ":")),
                    completed_at,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _apply_dispositions(connection: sqlite3.Connection) -> None:
    timestamp = _journal_timestamp(connection)
    connection.execute(
        "UPDATE users SET disabled_at=? WHERE disabled_at IS NULL AND id NOT IN "
        "(SELECT user_id FROM github_accounts WHERE user_id IS NOT NULL "
        "AND github_user_id IS NOT NULL AND disconnected_at IS NULL)",
        (timestamp,),
    )
    connection.execute("UPDATE api_tokens SET revoked_at=? WHERE revoked_at IS NULL", (timestamp,))
    connection.execute(
        "UPDATE projects SET lifecycle_state='legacy_unbound', hidden=1 WHERE github_repository_id IS NULL"
    )
    connection.execute("UPDATE projects SET lifecycle_state='active' WHERE github_repository_id IS NOT NULL")
    connection.execute(
        "UPDATE project_memberships SET expires_at=? WHERE source='manual' AND expires_at IS NULL",
        (timestamp,),
    )
    connection.execute("DELETE FROM project_memberships WHERE source='github'")
    connection.execute("UPDATE runs SET legacy_retained=1 WHERE origin='server'")


def _migrate_run_ids(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA defer_foreign_keys=ON")
    rows = connection.execute(
        "SELECT r.run_id, p.github_repository_id, r.github_run_id, r.github_run_attempt "
        "FROM runs r JOIN projects p ON p.id=r.project_id "
        "WHERE r.origin='github-actions' ORDER BY r.run_id"
    ).fetchall()
    tables = _tables(connection)
    for row in rows:
        old = str(row["run_id"])
        new = f"gh-{int(row['github_repository_id'])}-{int(row['github_run_id'])}-{int(row['github_run_attempt'])}"
        if old == new:
            continue
        connection.execute("UPDATE runs SET run_id=? WHERE run_id=?", (new, old))
        for table in _RUN_CHILD_TABLES:
            if table in tables and "run_id" in _columns(connection, table):
                connection.execute(f'UPDATE "{table}" SET run_id=? WHERE run_id=?', (new, old))


def _validate_cutover(connection: sqlite3.Connection, cutover_at: str) -> None:
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise IdentityCutoverError("foreign-key validation failed")
    checks = (
        (
            "SELECT count(*) FROM users WHERE disabled_at IS NULL AND id NOT IN "
            "(SELECT user_id FROM github_accounts WHERE user_id IS NOT NULL "
            "AND github_user_id IS NOT NULL AND disconnected_at IS NULL)",
            (),
        ),
        ("SELECT count(*) FROM api_tokens WHERE revoked_at IS NULL", ()),
        (
            "SELECT count(*) FROM projects WHERE github_repository_id IS NULL "
            "AND (lifecycle_state!='legacy_unbound' OR hidden!=1)",
            (),
        ),
        ("SELECT count(*) FROM project_memberships WHERE source='github'", ()),
        (
            "SELECT count(*) FROM project_memberships WHERE source='manual' AND (expires_at IS NULL OR expires_at>?)",
            (cutover_at,),
        ),
        (
            "SELECT count(*) FROM runs WHERE origin='server' AND legacy_retained!=1",
            (),
        ),
        (
            "SELECT count(*) FROM runs r JOIN projects p ON p.id=r.project_id "
            "WHERE r.origin='github-actions' AND r.run_id != "
            "('gh-' || p.github_repository_id || '-' || r.github_run_id || '-' || r.github_run_attempt)",
            (),
        ),
        (
            "SELECT count(*) FROM project_memberships m LEFT JOIN github_accounts a "
            "ON a.user_id=m.user_id WHERE m.source='github_app' AND "
            "(m.expires_at IS NULL OR a.github_user_id IS NULL OR a.disconnected_at IS NOT NULL)",
            (),
        ),
    )
    if any(int(connection.execute(sql, parameters).fetchone()[0]) for sql, parameters in checks):
        raise IdentityCutoverError("cutover disposition validation failed")


def _state(connection: sqlite3.Connection) -> tuple[dict[str, int], str]:
    counts = {
        "users": _count(connection, "users"),
        "disabled_users": _scalar(connection, "SELECT count(*) FROM users WHERE disabled_at IS NOT NULL"),
        "projects": _count(connection, "projects"),
        "legacy_unbound_projects": _scalar(
            connection, "SELECT count(*) FROM projects WHERE lifecycle_state='legacy_unbound'"
        ),
        "runs": _count(connection, "runs"),
        "legacy_server_runs": _scalar(connection, "SELECT count(*) FROM runs WHERE legacy_retained=1"),
        "active_api_tokens": _scalar(connection, "SELECT count(*) FROM api_tokens WHERE revoked_at IS NULL"),
        "foreign_key_violations": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    }
    opaque_state = {
        "counts": counts,
        "user_ids": [row[0] for row in connection.execute("SELECT id FROM users ORDER BY id")],
        "project_ids": [row[0] for row in connection.execute("SELECT id FROM projects ORDER BY id")],
        "run_ids": [row[0] for row in connection.execute("SELECT run_id FROM runs ORDER BY run_id")],
    }
    checksum = hashlib.sha256(json.dumps(opaque_state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return counts, checksum


def _completed_phases(connection: sqlite3.Connection, expected_checksum: str) -> set[str]:
    rows = connection.execute("SELECT phase, preflight_checksum FROM identity_migration_journal").fetchall()
    if any(str(row["preflight_checksum"]) != expected_checksum for row in rows):
        raise IdentityCutoverError("migration journal checksum mismatch")
    completed = {str(row["phase"]) for row in rows}
    if completed and completed != set(PHASES[: len(completed)]):
        raise IdentityCutoverError("migration journal phases are not contiguous")
    return completed


def _require_cutover_schema(connection: sqlite3.Connection) -> None:
    tables = _tables(connection)
    required = {
        "alembic_version",
        "identity_migration_journal",
        "users",
        "github_accounts",
        "projects",
        "project_memberships",
        "runs",
        "api_tokens",
    }
    if not required.issubset(tables):
        raise IdentityCutoverError("database is missing identity cutover tables")
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if revision is None or str(revision[0]) not in SUPPORTED_SCHEMA_REVISIONS:
        raise IdentityCutoverError("database is not at the identity cutover revision")


def _journal_timestamp(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT completed_at FROM identity_migration_journal WHERE phase='preflight_verified'"
    ).fetchone()
    if row is None:
        raise IdentityCutoverError("preflight journal phase is missing")
    return str(row[0])


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _count(connection: sqlite3.Connection, table: str) -> int:
    return _scalar(connection, f'SELECT count(*) FROM "{table}"')


def _scalar(connection: sqlite3.Connection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    return int(row[0]) if row is not None else 0


def _validated_database(database: Path) -> Path:
    if database.is_symlink():
        raise IdentityCutoverError("database path must not be a symlink")
    try:
        path = database.resolve(strict=True)
        mode = path.stat().st_mode
    except OSError as exc:
        raise IdentityCutoverError("database must be an existing regular file") from exc
    if not stat.S_ISREG(mode):
        raise IdentityCutoverError("database must be an existing regular file")
    return path


def _utc_timestamp(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IdentityCutoverError("cutover timestamp must include a timezone")
    return value.astimezone(dt.timezone.utc).isoformat()


__all__ = ["MIGRATION_REVISION", "PHASES", "run_identity_cutover"]
