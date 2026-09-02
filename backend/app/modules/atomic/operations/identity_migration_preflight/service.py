"""Read-only, repeatable inventory for the GitHub identity cutover."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from .models import IdentityMigrationPreflight, PreflightConflict


PREFLIGHT_SCHEMA = "assurance-scan-github-identity-preflight-v1"


class IdentityPreflightError(RuntimeError):
    """The database cannot be safely inventoried."""


def inspect_identity_migration(database: Path) -> IdentityMigrationPreflight:
    """Inspect identity/run disposition without mutating or exposing user data."""

    path = _validated_database(database)
    uri = f"file:{quote(str(path))}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            tables = _tables(connection)
            _require_tables(tables)
            revision = _revision(connection, tables)
            user_ids = _integer_ids(connection, "users", "id")
            linked_user_ids, identity_conflicts = _github_identities(connection, tables)
            project_ids = _integer_ids(connection, "projects", "id")
            bound_project_ids, project_conflicts = _projects(connection)
            run_inventory, run_conflicts = _runs(connection)
            membership_counts = _membership_counts(connection, tables)
            foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise IdentityPreflightError("database could not be inspected") from exc

    conflicts = [*identity_conflicts, *project_conflicts, *run_conflicts]
    if foreign_key_rows:
        conflicts.append(
            PreflightConflict(
                "foreign_key_violation",
                tuple(sorted(f"{row[0]}:{row[1]}" for row in foreign_key_rows)),
            )
        )
    linked_sorted = sorted(linked_user_ids)
    unlinked_sorted = sorted(set(user_ids) - linked_user_ids)
    bound_sorted = sorted(bound_project_ids)
    unbound_sorted = sorted(set(project_ids) - bound_project_ids)
    counts = {
        "users": len(user_ids),
        "linked_users": len(linked_sorted),
        "unlinked_users": len(unlinked_sorted),
        "projects": len(project_ids),
        "bound_projects": len(bound_sorted),
        "unbound_projects": len(unbound_sorted),
        "migratable_github_runs": len(run_inventory["migratable_github_run_ids"]),
        "server_runs": len(run_inventory["server_run_ids"]),
        "local_runs": len(run_inventory["local_run_ids"]),
    }
    stable = {
        "schema": PREFLIGHT_SCHEMA,
        "schema_revision": revision,
        "linked_user_ids": linked_sorted,
        "unlinked_user_ids": unlinked_sorted,
        "bound_project_ids": bound_sorted,
        "unbound_project_ids": unbound_sorted,
        "counts": counts,
        "membership_counts": membership_counts,
        **run_inventory,
        "conflicts": [
            {"code": item.code, "row_ids": list(item.row_ids)}
            for item in sorted(conflicts, key=lambda item: (item.code, item.row_ids))
        ],
    }
    checksum = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return IdentityMigrationPreflight(
        schema=PREFLIGHT_SCHEMA,
        schema_revision=revision,
        linked_user_ids=tuple(linked_sorted),
        unlinked_user_ids=tuple(unlinked_sorted),
        bound_project_ids=tuple(bound_sorted),
        unbound_project_ids=tuple(unbound_sorted),
        counts=counts,
        membership_counts=membership_counts,
        migratable_github_run_ids=tuple(run_inventory["migratable_github_run_ids"]),
        server_run_ids=tuple(run_inventory["server_run_ids"]),
        local_run_ids=tuple(run_inventory["local_run_ids"]),
        conflicts=tuple(sorted(conflicts, key=lambda item: (item.code, item.row_ids))),
        blocked=bool(conflicts),
        checksum=checksum,
    )


def _validated_database(database: Path) -> Path:
    if database.is_symlink():
        raise IdentityPreflightError("database path must not be a symlink")
    try:
        path = database.resolve(strict=True)
        mode = path.stat().st_mode
    except OSError as exc:
        raise IdentityPreflightError("database must be an existing regular file") from exc
    if not stat.S_ISREG(mode):
        raise IdentityPreflightError("database must be an existing regular file")
    return path


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _require_tables(tables: set[str]) -> None:
    missing = {"users", "projects", "runs"} - tables
    if missing:
        raise IdentityPreflightError("database is missing required application tables")


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _revision(connection: sqlite3.Connection, tables: set[str]) -> str | None:
    if "alembic_version" not in tables:
        return None
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return str(row[0]) if row else None


def _integer_ids(connection: sqlite3.Connection, table: str, column: str) -> set[int]:
    return {int(row[0]) for row in connection.execute(f'SELECT "{column}" FROM "{table}"')}


def _github_identities(
    connection: sqlite3.Connection, tables: set[str]
) -> tuple[set[int], list[PreflightConflict]]:
    if "github_accounts" not in tables:
        return set(), []
    columns = _columns(connection, "github_accounts")
    if not {"id", "user_id", "github_user_id"}.issubset(columns):
        return set(), []
    rows = connection.execute(
        "SELECT id, user_id, github_user_id FROM github_accounts "
        "WHERE user_id IS NOT NULL AND github_user_id IS NOT NULL"
    ).fetchall()
    linked = {int(row["user_id"]) for row in rows}
    conflicts: list[PreflightConflict] = []
    for field, code in (
        ("user_id", "user_has_multiple_github_identities"),
        ("github_user_id", "github_identity_has_multiple_users"),
    ):
        counts = Counter(str(row[field]) for row in rows)
        duplicated = {value for value, count in counts.items() if count > 1}
        if duplicated:
            conflicts.append(
                PreflightConflict(
                    code,
                    tuple(sorted(str(row["id"]) for row in rows if str(row[field]) in duplicated)),
                )
            )
    return linked, conflicts


def _projects(
    connection: sqlite3.Connection,
) -> tuple[set[int], list[PreflightConflict]]:
    columns = _columns(connection, "projects")
    if "github_repository_id" not in columns:
        return set(), []
    rows = connection.execute(
        "SELECT id, github_repository_id FROM projects ORDER BY id"
    ).fetchall()
    bound = {int(row["id"]) for row in rows if row["github_repository_id"] is not None}
    counts = Counter(
        str(row["github_repository_id"])
        for row in rows
        if row["github_repository_id"] is not None
    )
    duplicated = {value for value, count in counts.items() if count > 1}
    conflicts = []
    if duplicated:
        conflicts.append(
            PreflightConflict(
                "repository_identity_conflict",
                tuple(
                    sorted(
                        str(row["id"])
                        for row in rows
                        if str(row["github_repository_id"]) in duplicated
                    )
                ),
            )
        )
    return bound, conflicts


def _runs(
    connection: sqlite3.Connection,
) -> tuple[dict[str, list[str]], list[PreflightConflict]]:
    columns = _columns(connection, "runs")
    required = {
        "run_id",
        "project_id",
        "origin",
        "commit_sha",
        "github_run_id",
        "github_run_number",
        "github_run_attempt",
    }
    if not required.issubset(columns):
        raise IdentityPreflightError("run provenance columns are not migration-ready")
    rows = connection.execute(
        "SELECT r.run_id, r.origin, r.commit_sha, r.github_run_id, "
        "r.github_run_number, r.github_run_attempt, p.github_repository_id "
        "FROM runs r JOIN projects p ON p.id = r.project_id ORDER BY r.run_id"
    ).fetchall()
    github = [row for row in rows if row["origin"] == "github-actions"]
    sufficient = [
        row
        for row in github
        if all(
            row[field] is not None
            for field in (
                "commit_sha",
                "github_run_id",
                "github_run_number",
                "github_run_attempt",
                "github_repository_id",
            )
        )
    ]
    insufficient = sorted(
        str(row["run_id"]) for row in github if row not in sufficient
    )
    keys: dict[tuple[int, int, int], list[str]] = {}
    for row in sufficient:
        key = (
            int(row["github_repository_id"]),
            int(row["github_run_id"]),
            int(row["github_run_attempt"]),
        )
        keys.setdefault(key, []).append(str(row["run_id"]))
    duplicate_ids = sorted(
        run_id for run_ids in keys.values() if len(run_ids) > 1 for run_id in run_ids
    )
    conflicts = []
    if insufficient:
        conflicts.append(PreflightConflict("github_run_missing_provenance", tuple(insufficient)))
    if duplicate_ids:
        conflicts.append(PreflightConflict("duplicate_future_github_run_key", tuple(duplicate_ids)))
    return (
        {
            "migratable_github_run_ids": sorted(str(row["run_id"]) for row in sufficient),
            "server_run_ids": sorted(str(row["run_id"]) for row in rows if row["origin"] == "server"),
            "local_run_ids": sorted(str(row["run_id"]) for row in rows if row["origin"] == "local"),
        },
        conflicts,
    )


def _membership_counts(connection: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    counts = {"github": 0, "github_app": 0, "manual": 0}
    if "project_memberships" not in tables:
        return counts
    for source, count in connection.execute(
        "SELECT source, count(*) FROM project_memberships GROUP BY source"
    ):
        if str(source) in counts:
            counts[str(source)] = int(count)
    return counts


__all__ = ["IdentityPreflightError", "PREFLIGHT_SCHEMA", "inspect_identity_migration"]
