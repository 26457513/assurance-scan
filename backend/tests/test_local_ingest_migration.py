"""Forward-only WS2 claim fencing and tombstone migration tests."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
OLD_HEAD = "0021_project_identity_provenance"
NEW_HEAD = "0022_local_ingest_claims"


def _alembic(database: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["ASSURANCE_SCAN_DB_PATH"] = str(database)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        check=check,
        capture_output=True,
        text=True,
    )


def test_migration_aborts_before_replacing_unattributable_prerelease_claims(
    tmp_path: Path,
) -> None:
    database = tmp_path / "claim.sqlite"
    _alembic(database, "upgrade", OLD_HEAD)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (email, role, created_at) VALUES (?, 'user', CURRENT_TIMESTAMP)",
            ("owner@example.com",),
        )
        connection.execute(
            "INSERT INTO projects (tag, local_path, hidden, created_at) "
            "VALUES ('project', '/project', 0, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO ingest_requests "
            "(submitted_by_user_id, client_request_id, project_id, payload_hash, state, "
            "created_at, updated_at) VALUES (1, ?, 1, ?, 'failed', CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP)",
            ("0371d25c-5090-45f9-a833-216e49355964", "a" * 64),
        )
        connection.commit()

    result = _alembic(database, "upgrade", "head", check=False)

    assert result.returncode != 0
    assert "cannot attribute pre-release ingest claims" in result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            OLD_HEAD,
        )
        assert connection.execute("SELECT count(*) FROM ingest_requests").fetchone() == (1,)


def test_claim_schema_has_quota_fencing_and_tombstone_guards(tmp_path: Path) -> None:
    database = tmp_path / "schema.sqlite"
    _alembic(database, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        columns = {
            str(row[1]): row for row in connection.execute("PRAGMA table_info(ingest_requests)")
        }
        indexes = {
            str(row[1]) for row in connection.execute("PRAGMA index_list(ingest_requests)")
        }
        foreign_keys = connection.execute("PRAGMA foreign_key_list(ingest_requests)").fetchall()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()

    assert revision == (NEW_HEAD,)
    assert columns["submitting_token_id"][3] == 1
    assert columns["accepted_bytes"][3] == 1
    assert {"lease_id", "tombstoned_at", "tombstone_expires_at"}.issubset(columns)
    assert {
        "ix_ingest_requests_token_created",
        "ix_ingest_requests_user_created",
    }.issubset(indexes)
    assert any(row[2] == "runs" and row[3] == "run_id" and row[6] == "SET NULL" for row in foreign_keys)

