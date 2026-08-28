"""WS1 project-identity/provenance migration and model contract tests."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.infrastructure.db.models import ApiToken, Base, IngestRequest, Project, Run, User


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
LEGACY_HEAD = "0020_snapshot_source_branch"
NEW_HEAD = "0021_project_identity_provenance"


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


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, tuple]:
    return {str(row[1]): row for row in connection.execute(f'PRAGMA table_info("{table}")')}


def test_github_orphan_is_projected_to_one_deterministic_project(tmp_path: Path) -> None:
    database = tmp_path / "orphan.sqlite"
    _alembic(database, "upgrade", LEGACY_HEAD)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO runs "
            "(run_id, project_path, options_json, status, started_at, commit_sha, git_branch) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "gh-42",
                "github:Example/Widget",
                json.dumps({
                    "source": "github-actions",
                    "run_url": "https://github.com/Example/Widget/actions/runs/42",
                    "run_number": 7,
                    "event": "push",
                    "actor": "alice",
                }),
                "completed",
                "2026-08-28 10:00:00",
                "a" * 40,
                "main",
            ),
        )
        connection.commit()

    _alembic(database, "upgrade", "head")

    with sqlite3.connect(database) as connection:
        project = connection.execute(
            "SELECT id, tag, local_path, github_repo, github_repo_key FROM projects"
        ).fetchone()
        run = connection.execute(
            "SELECT project_id, origin, repository_full_name_at_scan, "
            "working_tree_dirty, git_object_format, github_run_id FROM runs"
        ).fetchone()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert project == (1, "Widget", None, "Example/Widget", "example/widget")
    assert run == (1, "github-actions", "Example/Widget", 0, "sha1", 42)
    assert revision == (NEW_HEAD,)


def test_unregistered_local_history_aborts_before_schema_changes(tmp_path: Path) -> None:
    database = tmp_path / "unresolved.sqlite"
    _alembic(database, "upgrade", LEGACY_HEAD)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO runs (run_id, project_path, options_json, status, started_at) "
            "VALUES ('server-1', '/unregistered/project', '{}', 'completed', CURRENT_TIMESTAMP)"
        )
        connection.commit()

    result = _alembic(database, "upgrade", "head", check=False)

    assert result.returncode != 0
    assert "no exact registered local path" in result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (LEGACY_HEAD,)
        assert "project_path" in _columns(connection, "runs")
        assert "project_id" not in _columns(connection, "runs")


def test_ambiguous_normalized_github_registry_aborts(tmp_path: Path) -> None:
    database = tmp_path / "ambiguous.sqlite"
    _alembic(database, "upgrade", LEGACY_HEAD)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO projects (tag, local_path, github_repo, created_at, hidden) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP, 0)",
            (
                ("one", "/projects/one", "Example/Widget"),
                ("two", "/projects/two", "example/widget"),
            ),
        )
        connection.commit()

    result = _alembic(database, "upgrade", "head", check=False)

    assert result.returncode != 0
    assert "ambiguous_repository_keys" in result.stderr
    assert "example/widget" in result.stderr


def test_cutover_removes_every_persisted_project_path(tmp_path: Path) -> None:
    database = tmp_path / "schema.sqlite"
    _alembic(database, "upgrade", "head")
    path_keyed_before_cutover = (
        "catalogue_snapshots",
        "frs",
        "runs",
        "project_checkouts",
        "test_results",
        "evidence",
        "fr_state",
        "waivers",
        "finding_acceptances",
        "agent_actions",
        "compliance_mappings",
        "compliance_mapping_snapshots",
    )
    directly_project_scoped = (
        "catalogue_snapshots",
        "runs",
        "project_checkouts",
        "waivers",
        "finding_acceptances",
        "agent_actions",
        "compliance_mappings",
        "compliance_mapping_snapshots",
    )
    with sqlite3.connect(database) as connection:
        for table in path_keyed_before_cutover:
            assert "project_path" not in _columns(connection, table)
        for table in directly_project_scoped:
            assert "project_id" in _columns(connection, table)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_model_metadata_matches_token_and_identity_contract() -> None:
    assert Project.__table__.c.local_path.nullable
    assert not Run.__table__.c.project_id.nullable
    assert not Run.__table__.c.origin.nullable
    assert Run.__table__.c.working_tree_dirty.nullable
    assert getattr(Run.__table__.c.submitting_token_id.type, "length") == 36
    assert getattr(ApiToken.__table__.c.id.type, "length") == 36
    assert getattr(ApiToken.__table__.c.selector.type, "length") == 16
    assert getattr(ApiToken.__table__.c.secret_digest.type, "length") == 32
    assert User.__table__.c.disabled_at.nullable
    assert not IngestRequest.__table__.c.project_id.nullable
    assert "project_path" not in Run.__table__.c
    assert {
        "projects",
        "runs",
        "api_tokens",
        "ingest_requests",
    }.issubset(Base.metadata.tables)


@pytest.mark.parametrize("table", ["runs", "catalogue_snapshots", "waivers"])
def test_mandatory_project_foreign_keys_are_not_nullable(tmp_path: Path, table: str) -> None:
    database = tmp_path / f"{table}.sqlite"
    _alembic(database, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        assert _columns(connection, table)["project_id"][3] == 1
