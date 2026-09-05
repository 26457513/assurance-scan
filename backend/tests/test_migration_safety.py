"""Forward-only SQLite migration safety checks.

The production upgrade path is tested on both a fresh database and a copied,
representative older database. Downgrades are intentionally out of scope.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
LEGACY_REVISION = "0016_project_scan_ref"
HEAD_REVISION = "0039_finding_package_identity"


def _alembic(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["ASSURANCE_SCAN_DB_PATH"] = str(database)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _revision(database: Path) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row is not None
    return str(row[0])


def _tables(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _columns(database: Path, table: str) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def test_empty_database_migrates_forward_to_head(tmp_path: Path) -> None:
    database = tmp_path / "empty.sqlite"

    _alembic(database, "upgrade", "head")

    assert _revision(database) == HEAD_REVISION
    assert {
        "runs",
        "projects",
        "users",
        "project_checkouts",
        "source_contexts",
        "source_context_findings",
        "browser_sessions",
        "github_app_installations",
        "github_installation_repositories",
        "github_installation_states",
        "github_webhook_deliveries",
    }.issubset(_tables(database))
    assert {"organisations", "github_oauth_states", "identity_migration_journal"}.isdisjoint(
        _tables(database)
    )
    assert {
        "user_id",
        "github_user_id",
        "encrypted_user_token",
        "credential_key_id",
    }.issubset(_columns(database, "github_accounts"))
    assert {"email", "login", "token_encrypted"}.isdisjoint(
        _columns(database, "github_accounts")
    )
    assert {
        "github_installation_id",
        "github_owner_id",
        "repository_selection",
        "suspended_at",
        "deleted_at",
        "repositories_etag",
        "reconciliation_cursor",
    }.issubset(_columns(database, "github_app_installations"))
    assert {
        "github_installation_id",
        "github_repository_id",
        "project_id",
        "default_branch",
        "repository_verified_at",
        "removed_at",
    }.issubset(_columns(database, "github_installation_repositories"))
    assert {
        "github_installation_id",
        "attempt_count",
        "available_at",
        "lease_token",
        "lease_expires_at",
        "last_error_code",
    }.issubset(_columns(database, "github_webhook_deliveries"))


def test_copied_representative_database_dry_run_upgrade_and_backup_restore(tmp_path: Path) -> None:
    source = tmp_path / "representative-source.sqlite"
    dry_run_copy = tmp_path / "representative-dry-run.sqlite"
    backup = tmp_path / "representative.backup.sqlite"
    restored = tmp_path / "representative-restored.sqlite"

    _alembic(source, "upgrade", LEGACY_REVISION)
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO catalogue_snapshots (
                id, project_path, catalogue_version, snapshot_json,
                content_hash, created_at, tag, source_commit_sha
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "catalogue-snapshot-1",
                "/projects/representative",
                "1.0.0",
                "{}",
                "b" * 64,
                "2026-08-28 09:00:00",
                "baseline",
                "a" * 40,
            ),
        )
        connection.execute(
            """
            INSERT INTO runs (
                run_id, project_path, options_json, status, started_at,
                commit_sha, findings_json, git_branch
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "migration-safety-run",
                "/projects/representative",
                '{"scanners":["semgrep"]}',
                "completed",
                "2026-08-28 10:00:00",
                "a" * 40,
                "[]",
                "main",
            ),
        )
        connection.execute(
            "UPDATE runs SET catalogue_snapshot_id = ? WHERE run_id = ?",
            ("catalogue-snapshot-1", "migration-safety-run"),
        )
        connection.execute(
            """
            INSERT INTO scan_jobs (run_id, state, queued_at, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "migration-safety-run",
                "completed",
                "2026-08-28 09:59:00",
                "2026-08-28 10:00:00",
                "2026-08-28 10:01:00",
            ),
        )
        scanner_run = connection.execute(
            """
            INSERT INTO scanner_runs (
                run_id, scanner_kind, status, started_at, completed_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "migration-safety-run",
                "semgrep",
                "completed",
                "2026-08-28 10:00:00",
                "2026-08-28 10:01:00",
            ),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO scanner_artifacts (
                scanner_run_id, kind, content_blob, content_hash,
                size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (scanner_run, "sarif", b"{}", "c" * 64, 2, "2026-08-28 10:01:00"),
        )
        connection.execute(
            """
            INSERT INTO findings (
                run_id, scanner_kind, rule_id, severity, file_path,
                line_start, line_end, message, compliance_tags_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "migration-safety-run",
                "semgrep",
                "example.rule",
                "high",
                "src/example.py",
                10,
                10,
                "Representative finding",
                "[]",
                "2026-08-28 10:01:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO compliance_mapping_snapshots (
                id, project_path, content_hash, catalogue_content_hash,
                packs_json, mapping_doc_json, loaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "mapping-snapshot-1",
                "/projects/representative",
                "d" * 64,
                "b" * 64,
                "[]",
                "{}",
                "2026-08-28 09:30:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO projects (tag, local_path, github_repo, created_at, default_scan_ref)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "representative",
                "/projects/representative",
                "example/representative",
                "2026-08-28 09:00:00",
                "main",
            ),
        )
        connection.execute(
            "INSERT INTO users (email, role, created_at) VALUES (?, ?, ?)",
            ("user@example.test", "user", "2026-08-28 09:00:00"),
        )
        connection.execute(
            """
            INSERT INTO github_accounts (email, login, token_encrypted, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "legacy@example.test",
                "legacy-login",
                "legacy-encrypted-token",
                "2026-08-28 09:00:00",
            ),
        )
        connection.commit()

    shutil.copy2(source, dry_run_copy)
    _alembic(dry_run_copy, "upgrade", "head")

    # The dry run operates only on a copy and proves the source remains intact.
    assert _revision(source) == LEGACY_REVISION
    assert _revision(dry_run_copy) == HEAD_REVISION
    with sqlite3.connect(dry_run_copy) as connection:
        migrated = connection.execute(
            "SELECT project_id, origin, commit_sha, git_branch, working_tree_dirty FROM runs WHERE run_id = ?",
            ("migration-safety-run",),
        ).fetchone()
        related_counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "catalogue_snapshots",
                "compliance_mapping_snapshots",
                "findings",
                "projects",
                "scan_jobs",
                "scanner_artifacts",
                "scanner_runs",
                "users",
            )
        }
        github_account_count = connection.execute("SELECT count(*) FROM github_accounts").fetchone()
    assert migrated == (1, "server", "a" * 40, "main", None)
    assert all(count >= 1 for count in related_counts.values())
    assert github_account_count == (0,)

    # Exercise SQLite's online backup API, then restore into a distinct file.
    with sqlite3.connect(dry_run_copy) as source_connection, sqlite3.connect(backup) as backup_connection:
        source_connection.backup(backup_connection)
    shutil.copy2(backup, restored)

    assert _revision(restored) == HEAD_REVISION
    with sqlite3.connect(restored) as connection:
        restored_row = connection.execute(
            "SELECT status, project_id, origin FROM runs WHERE run_id = ?",
            ("migration-safety-run",),
        ).fetchone()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert restored_row == ("completed", 1, "server")
    assert integrity == ("ok",)
    assert foreign_key_violations == []
