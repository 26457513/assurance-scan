"""Read-only identity migration inventory and ambiguity guards."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.modules.atomic.operations.identity_migration_preflight import (
    IdentityPreflightError,
    inspect_identity_migration,
)


def _database(path: Path, *, conflicts: bool = False) -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num TEXT NOT NULL);
            INSERT INTO alembic_version VALUES ('0025_finding_source_contexts');
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL);
            CREATE TABLE projects (
              id INTEGER PRIMARY KEY,
              github_repository_id INTEGER,
              github_repo TEXT
            );
            CREATE TABLE github_accounts (
              id INTEGER PRIMARY KEY,
              user_id INTEGER,
              github_user_id INTEGER,
              login_at_last_verify TEXT,
              FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE runs (
              run_id TEXT PRIMARY KEY,
              project_id INTEGER NOT NULL,
              origin TEXT NOT NULL,
              commit_sha TEXT,
              github_run_id INTEGER,
              github_run_number INTEGER,
              github_run_attempt INTEGER,
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            CREATE TABLE project_memberships (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL,
              project_id INTEGER NOT NULL,
              source TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id),
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            INSERT INTO users VALUES (1, 'private-one@example.test');
            INSERT INTO users VALUES (2, 'private-two@example.test');
            INSERT INTO projects VALUES (10, 4242, 'private/repository');
            INSERT INTO projects VALUES (20, NULL, 'legacy/repository');
            INSERT INTO github_accounts VALUES (100, 1, 9001, 'private-login');
            INSERT INTO runs VALUES ('gh-old', 10, 'github-actions', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 70, 26, 1);
            INSERT INTO runs VALUES ('server-old', 10, 'server', NULL, NULL, NULL, NULL);
            INSERT INTO runs VALUES ('local-old', 10, 'local', 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', NULL, NULL, NULL);
            INSERT INTO project_memberships VALUES (1, 1, 10, 'github');
            INSERT INTO project_memberships VALUES (2, 1, 20, 'manual');
            """
        )
        if conflicts:
            connection.executescript(
                """
                INSERT INTO github_accounts VALUES (101, 1, 9002, 'another-login');
                INSERT INTO github_accounts VALUES (102, 2, 9001, 'third-login');
                INSERT INTO projects VALUES (30, 4242, 'conflicting/repository');
                INSERT INTO runs VALUES ('gh-duplicate', 10, 'github-actions', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 70, 27, 1);
                INSERT INTO runs VALUES ('gh-incomplete', 10, 'github-actions', NULL, 71, 28, 1);
                """
            )
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                "INSERT INTO project_memberships VALUES (3, 999, 10, 'manual')"
            )
        connection.commit()
    return path


def test_preflight_is_read_only_repeatable_and_contains_only_opaque_ids(tmp_path: Path) -> None:
    database = _database(tmp_path / "candidate.sqlite")
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    first = inspect_identity_migration(database)
    second = inspect_identity_migration(database)

    assert first == second
    assert first.checksum == second.checksum
    assert first.blocked is False
    assert first.linked_user_ids == (1,)
    assert first.unlinked_user_ids == (2,)
    assert first.bound_project_ids == (10,)
    assert first.unbound_project_ids == (20,)
    assert first.counts == {
        "users": 2,
        "linked_users": 1,
        "unlinked_users": 1,
        "projects": 2,
        "bound_projects": 1,
        "unbound_projects": 1,
        "migratable_github_runs": 1,
        "server_runs": 1,
        "local_runs": 1,
    }
    assert first.membership_counts == {"github": 1, "github_app": 0, "manual": 1}
    assert first.migratable_github_run_ids == ("gh-old",)
    assert first.server_run_ids == ("server-old",)
    assert first.local_run_ids == ("local-old",)
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    rendered = json.dumps(first.to_document(), sort_keys=True)
    assert "private-one" not in rendered
    assert "private-login" not in rendered
    assert "private/repository" not in rendered


def test_preflight_blocks_every_ambiguous_identity_and_run_key(tmp_path: Path) -> None:
    report = inspect_identity_migration(_database(tmp_path / "conflicts.sqlite", conflicts=True))
    codes = {conflict.code for conflict in report.conflicts}

    assert report.blocked is True
    assert codes == {
        "duplicate_future_github_run_key",
        "foreign_key_violation",
        "github_identity_has_multiple_users",
        "github_run_missing_provenance",
        "repository_identity_conflict",
        "user_has_multiple_github_identities",
    }
    assert next(
        item for item in report.conflicts if item.code == "repository_identity_conflict"
    ).row_ids == ("10", "30")


def test_legacy_email_keyed_github_rows_are_never_inferred_as_linked(tmp_path: Path) -> None:
    database = _database(tmp_path / "legacy.sqlite")
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE github_accounts")
        connection.execute(
            "CREATE TABLE github_accounts (id INTEGER PRIMARY KEY, email TEXT, token_encrypted TEXT)"
        )
        connection.execute(
            "INSERT INTO github_accounts VALUES (1, 'private-one@example.test', 'ciphertext')"
        )
        connection.commit()

    report = inspect_identity_migration(database)

    assert report.linked_user_ids == ()
    assert report.unlinked_user_ids == (1, 2)


def test_preflight_rejects_symlink_and_non_application_database(tmp_path: Path) -> None:
    database = _database(tmp_path / "candidate.sqlite")
    symlink = tmp_path / "linked.sqlite"
    symlink.symlink_to(database)
    with pytest.raises(IdentityPreflightError, match="symlink"):
        inspect_identity_migration(symlink)

    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(empty).close()
    with pytest.raises(IdentityPreflightError, match="required application tables"):
        inspect_identity_migration(empty)


def test_operator_cli_emits_json_and_uses_blocked_exit_status(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    script = backend_root / "scripts" / "identity-migration-preflight.py"
    ready = subprocess.run(
        [sys.executable, str(script), str(_database(tmp_path / "ready.sqlite"))],
        cwd=backend_root,
        check=False,
        capture_output=True,
        text=True,
    )
    blocked = subprocess.run(
        [
            sys.executable,
            str(script),
            str(_database(tmp_path / "blocked.sqlite", conflicts=True)),
        ],
        cwd=backend_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert ready.returncode == 0
    assert json.loads(ready.stdout)["blocked"] is False
    assert blocked.returncode == 2
    assert json.loads(blocked.stdout)["blocked"] is True
