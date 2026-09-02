"""Journalled identity cutover, restart and fail-closed tests."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.modules.atomic.operations.identity_migration_cutover import (
    IdentityCutoverError,
    PHASES,
    compare_rehearsal_documents,
    run_identity_cutover,
)
from app.modules.atomic.operations.identity_migration_preflight import (
    inspect_identity_migration,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
CUTOVER_AT = dt.datetime(2026, 9, 2, 15, 0, tzinfo=dt.timezone.utc)


def _alembic(database: Path) -> None:
    environment = os.environ.copy()
    environment["ASSURANCE_SCAN_DB_PATH"] = str(database)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _candidate(path: Path) -> Path:
    _alembic(path)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executemany(
            "INSERT INTO users (id,email,role,created_at) VALUES (?,?,?,?)",
            (
                (101, "linked@example.test", "user", CUTOVER_AT.isoformat()),
                (102, "unlinked@example.test", "user", CUTOVER_AT.isoformat()),
            ),
        )
        connection.execute(
            "INSERT INTO github_accounts "
            "(id,created_at,user_id,github_user_id,login_at_last_verify,"
            "encrypted_user_token,credential_key_id,linked_at,verified_at) "
            "VALUES (1,?,?,?,?,?,?,?,?)",
            (
                CUTOVER_AT.isoformat(),
                101,
                9001,
                "linked-login",
                "ciphertext",
                "primary",
                CUTOVER_AT.isoformat(),
                CUTOVER_AT.isoformat(),
            ),
        )
        connection.executemany(
            "INSERT INTO projects "
            "(id,tag,local_path,github_repo,github_repo_key,github_repository_id,"
            "hidden,local_run_counter,created_at,lifecycle_state) "
            "VALUES (?,?,?,?,?,?,0,0,?,'active')",
            (
                (10, "bound", None, "org/bound", "org/bound", 4242, CUTOVER_AT.isoformat()),
                (20, "local-only", "/project/local", None, None, None, CUTOVER_AT.isoformat()),
            ),
        )
        connection.executemany(
            "INSERT INTO runs "
            "(run_id,project_id,options_json,status,started_at,commit_sha,git_branch,"
            "git_object_format,origin,working_tree_dirty,submitted_by_user_id,"
            "github_run_id,github_run_number,github_run_attempt,legacy_retained) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (
                (
                    "gh-old",
                    10,
                    "{}",
                    "completed",
                    CUTOVER_AT.isoformat(),
                    "a" * 40,
                    "main",
                    "sha1",
                    "github-actions",
                    0,
                    None,
                    70,
                    26,
                    1,
                ),
                (
                    "server-old",
                    10,
                    "{}",
                    "completed",
                    CUTOVER_AT.isoformat(),
                    None,
                    None,
                    None,
                    "server",
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            ),
        )
        connection.execute(
            "INSERT INTO scan_jobs (run_id,state,queued_at) VALUES (?,?,?)",
            ("gh-old", "completed", CUTOVER_AT.isoformat()),
        )
        connection.execute(
            "INSERT INTO api_tokens "
            "(id,user_id,label,label_key,selector,secret_digest,scope,token_version,"
            "expires_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "00000000-0000-4000-8000-000000000001",
                101,
                "Laptop",
                "laptop",
                "selector00000001",
                bytes(32),
                "scans:upload",
                1,
                (CUTOVER_AT + dt.timedelta(days=1)).isoformat(),
                CUTOVER_AT.isoformat(),
            ),
        )
        connection.executemany(
            "INSERT INTO project_memberships "
            "(user_id,project_id,permission,source,verified_at,expires_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                (101, 10, "view", "github", CUTOVER_AT.isoformat(), None),
                (102, 10, "view", "manual", CUTOVER_AT.isoformat(), None),
                (
                    101,
                    10,
                    "upload",
                    "github_app",
                    CUTOVER_AT.isoformat(),
                    (CUTOVER_AT + dt.timedelta(minutes=5)).isoformat(),
                ),
            ),
        )
        connection.commit()
    return path


def test_cutover_transforms_and_resumes_before_confirmed_switch(tmp_path: Path) -> None:
    database = _candidate(tmp_path / "candidate.sqlite")
    preflight = inspect_identity_migration(database)
    assert preflight.blocked is False

    rehearsed = run_identity_cutover(
        database,
        expected_preflight_checksum=preflight.checksum,
        cutover_at=CUTOVER_AT,
        confirm_switch=False,
    )
    assert rehearsed.status == "validated"
    assert rehearsed.completed_phases == PHASES[:-1]

    # Removing the final pre-switch markers simulates interruption; repeated
    # transformations are idempotent and reproduce the same state checksum.
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM identity_migration_journal WHERE phase IN ('run_ids_migrated','validated')")
        connection.commit()
    resumed = run_identity_cutover(
        database,
        expected_preflight_checksum=preflight.checksum,
        cutover_at=CUTOVER_AT,
        confirm_switch=True,
    )
    assert resumed.status == "switch_complete"
    assert resumed.completed_phases == PHASES
    assert resumed.state_checksum == rehearsed.state_checksum

    with sqlite3.connect(database) as connection:
        user = connection.execute("SELECT disabled_at FROM users WHERE id=102").fetchone()
        project = connection.execute("SELECT hidden,lifecycle_state FROM projects WHERE id=20").fetchone()
        runs = connection.execute("SELECT run_id,legacy_retained FROM runs ORDER BY run_id").fetchall()
        child = connection.execute("SELECT run_id FROM scan_jobs").fetchone()
        active_tokens = connection.execute("SELECT count(*) FROM api_tokens WHERE revoked_at IS NULL").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert user == (CUTOVER_AT.isoformat(),)
    assert project == (1, "legacy_unbound")
    assert runs == [
        ("gh-4242-70-1", 0),
        ("server-old", 1),
    ]
    assert child == ("gh-4242-70-1",)
    assert active_tokens == (0,)
    assert foreign_keys == []


def test_cutover_rejects_wrong_checksum_without_journal(tmp_path: Path) -> None:
    database = _candidate(tmp_path / "candidate.sqlite")
    with pytest.raises(IdentityCutoverError, match="does not match"):
        run_identity_cutover(
            database,
            expected_preflight_checksum="0" * 64,
            cutover_at=CUTOVER_AT,
            confirm_switch=False,
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM identity_migration_journal").fetchone() == (0,)


def test_rehearsal_comparison_ignores_runtime_metrics_but_rejects_state_drift(
    tmp_path: Path,
) -> None:
    first = _validated_rehearsal(tmp_path / "first.sqlite")
    second = _validated_rehearsal(tmp_path / "second.sqlite")
    second["duration_ms"] = int(first["duration_ms"]) + 50
    second["available_free_bytes"] = int(first["available_free_bytes"]) - 1

    matched = compare_rehearsal_documents(first, second)

    assert matched["status"] == "matched"
    drifted = dict(second)
    counts = second["counts"]
    assert isinstance(counts, dict)
    drifted["counts"] = {**counts, "runs": 99}
    with pytest.raises(IdentityCutoverError, match="identical migration evidence"):
        compare_rehearsal_documents(first, drifted)


def _validated_rehearsal(database: Path) -> dict[str, object]:
    _candidate(database)
    checksum = inspect_identity_migration(database).checksum
    return run_identity_cutover(
        database,
        expected_preflight_checksum=checksum,
        cutover_at=CUTOVER_AT,
        confirm_switch=False,
    ).to_document()
