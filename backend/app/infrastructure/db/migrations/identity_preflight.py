"""Deterministic preflight for the 0021 project-identity clean cutover.

The migration imports this module, and operators can run it directly against a
copy of the production SQLite database.  It never guesses from basenames.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.modules.atomic.provenance.repository_identity import (
    InvalidRepositoryIdentityError,
    normalize_github_repository_key,
    parse_github_repository,
)


PATH_TABLES = (
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


class IdentityPreflightError(RuntimeError):
    """Raised with a machine-readable report when cutover cannot proceed."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(json.dumps(report, indent=2, sort_keys=True))


@dataclass(frozen=True)
class ProjectCreation:
    """One deterministic registry row required for legacy GitHub data."""

    repository: str
    repository_key: str
    tag: str


@dataclass(frozen=True)
class IdentityPlan:
    """Resolved legacy identities plus projects that the migration must add."""

    path_targets: dict[str, str]
    projects_to_create: tuple[ProjectCreation, ...]
    checkout_users: dict[str, int]
    run_origins: dict[str, str]
    report: dict[str, Any]


def _table_exists(connection: Connection, table: str) -> bool:
    return sa.inspect(connection).has_table(table)


def canonical_repository(value: str) -> tuple[str, str]:
    """Return preserved ``owner/repo`` and its lowercase comparison key."""
    raw = value.strip()
    if raw.startswith("github:"):
        raw = raw[7:]
    try:
        repository = parse_github_repository(raw)
        if repository is None:
            raise InvalidRepositoryIdentityError("GitHub repository is required")
        return repository, normalize_github_repository_key(repository)
    except InvalidRepositoryIdentityError as exc:
        raise ValueError(str(exc)) from exc


def _legacy_paths(connection: Connection) -> dict[str, list[str]]:
    by_path: dict[str, list[str]] = {}
    inspector = sa.inspect(connection)
    for table in PATH_TABLES:
        if not inspector.has_table(table):
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "project_path" not in columns:
            continue
        rows = connection.execute(
            sa.text(f'SELECT DISTINCT project_path FROM "{table}" WHERE project_path IS NOT NULL')
        )
        for (path,) in rows:
            by_path.setdefault(str(path), []).append(table)
    return by_path


def _project_rows(connection: Connection) -> list[dict[str, Any]]:
    if not _table_exists(connection, "projects"):
        return []
    return [dict(row) for row in connection.execute(sa.text(
        "SELECT id, tag, local_path, github_repo, hidden FROM projects ORDER BY id"
    )).mappings()]


def _tag_for(repository: str, used_tags: set[str]) -> str:
    owner, name = repository.split("/", 1)
    candidates = (name, f"{owner}-{name}")
    for candidate in candidates:
        if candidate not in used_tags:
            used_tags.add(candidate)
            return candidate
    suffix = hashlib.sha256(repository.lower().encode()).hexdigest()[:8]
    candidate = f"{owner}-{name}-{suffix}"
    used_tags.add(candidate)
    return candidate


def _classify_origin(run_id: str, project_path: str, options_json: str) -> str:
    try:
        options = json.loads(options_json or "{}")
    except (TypeError, json.JSONDecodeError):
        options = {}
    source = options.get("source") if isinstance(options, dict) else None
    if source == "local":
        raise ValueError("historical local origin is unsupported before WS1")
    if source == "github-actions" or run_id.startswith("gh-"):
        return "github-actions"
    if source not in (None, "", "server"):
        raise ValueError(f"unsupported historical origin marker {source!r}")
    if project_path.startswith("github:"):
        raise ValueError("github project path lacks GitHub Actions origin evidence")
    return "server"


def build_identity_plan(connection: Connection) -> IdentityPlan:
    """Inspect a revision-0020 database and return its deterministic cutover plan."""
    paths = _legacy_paths(connection)
    projects = _project_rows(connection)
    existing_tags = {str(project["tag"]) for project in projects}
    local_candidates: dict[str, set[int]] = {}
    repository_candidates: dict[str, set[int]] = {}
    invalid_projects: list[dict[str, Any]] = []
    duplicate_repository_ids: list[dict[str, Any]] = []

    for project in projects:
        project_id = int(project["id"])
        local_path = project.get("local_path")
        if local_path:
            local_candidates.setdefault(str(local_path), set()).add(project_id)
        repository_value = project.get("github_repo")
        if not repository_value and isinstance(local_path, str) and local_path.startswith("github:"):
            repository_value = local_path
        if repository_value:
            try:
                _, key = canonical_repository(str(repository_value))
            except ValueError as exc:
                invalid_projects.append({"project_id": project_id, "reason": str(exc)})
            else:
                repository_candidates.setdefault(key, set()).add(project_id)

    ambiguous_repository_keys = [
        {"repository_key": key, "project_ids": sorted(ids)}
        for key, ids in sorted(repository_candidates.items())
        if len(ids) > 1
    ]
    path_targets: dict[str, str] = {}
    matched: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    tombstoned: list[dict[str, Any]] = []
    creations_by_key: dict[str, ProjectCreation] = {}
    projects_by_id = {int(project["id"]): project for project in projects}

    for path, tables in sorted(paths.items()):
        candidates = set(local_candidates.get(path, ()))
        repository: str | None = None
        repository_key: str | None = None
        if path.startswith("github:"):
            try:
                repository, repository_key = canonical_repository(path)
            except ValueError as exc:
                unresolved.append({"project_path": path, "tables": tables, "reason": str(exc)})
                continue
            candidates.update(repository_candidates.get(repository_key, ()))
        if len(candidates) > 1:
            ambiguous.append({
                "project_path": path,
                "tables": tables,
                "project_ids": sorted(candidates),
            })
            continue
        if len(candidates) == 1:
            project_id = next(iter(candidates))
            if bool(projects_by_id[project_id].get("hidden")):
                tombstoned.append({
                    "project_path": path,
                    "tables": tables,
                    "project_id": project_id,
                })
                continue
            target = f"project:{project_id}"
            path_targets[path] = target
            matched.append({"project_path": path, "tables": tables, "project_id": project_id})
            continue
        if repository is None or repository_key is None:
            unresolved.append({
                "project_path": path,
                "tables": tables,
                "reason": "no exact registered local path",
            })
            continue
        creation = creations_by_key.get(repository_key)
        if creation is None:
            creation = ProjectCreation(
                repository=repository,
                repository_key=repository_key,
                tag=_tag_for(repository, existing_tags),
            )
            creations_by_key[repository_key] = creation
        path_targets[path] = f"repository:{repository_key}"

    checkout_users: dict[str, int] = {}
    unresolved_checkouts: list[dict[str, Any]] = []
    if _table_exists(connection, "project_checkouts"):
        users_by_email: dict[str, list[int]] = {}
        if _table_exists(connection, "users"):
            for user_id, email in connection.execute(sa.text("SELECT id, email FROM users")):
                users_by_email.setdefault(str(email).lower(), []).append(int(user_id))
        for checkout_id, email in connection.execute(sa.text(
            "SELECT id, user_email FROM project_checkouts ORDER BY id"
        )):
            matches = users_by_email.get(str(email).strip().lower(), [])
            if len(matches) != 1:
                unresolved_checkouts.append({
                    "checkout_id": int(checkout_id),
                    "user_email": str(email),
                    "matching_user_ids": matches,
                })
            else:
                checkout_users[str(int(checkout_id))] = matches[0]

    run_origins: dict[str, str] = {}
    invalid_runs: list[dict[str, Any]] = []
    if _table_exists(connection, "runs"):
        rows = connection.execute(sa.text(
            "SELECT run_id, project_path, options_json, commit_sha FROM runs ORDER BY run_id"
        ))
        for run_id, project_path, options_json, commit_sha in rows:
            try:
                origin = _classify_origin(str(run_id), str(project_path), str(options_json or "{}"))
                if commit_sha is not None:
                    commit = str(commit_sha)
                    if len(commit) not in (40, 64) or re.fullmatch(r"[0-9a-f]+", commit) is None:
                        raise ValueError("commit SHA is not lowercase 40/64-character hexadecimal")
                if origin == "github-actions":
                    options = json.loads(str(options_json or "{}"))
                    external_id = options.get("github_run_id") if isinstance(options, dict) else None
                    if external_id is None and str(run_id).startswith("gh-"):
                        external_id = str(run_id)[3:]
                    if external_id is None or not str(external_id).isdigit():
                        raise ValueError("GitHub Actions run lacks a numeric GitHub run ID")
                    if commit_sha is None:
                        raise ValueError("GitHub Actions run lacks a scanned commit SHA")
            except ValueError as exc:
                invalid_runs.append({"run_id": str(run_id), "reason": str(exc)})
            else:
                run_origins[str(run_id)] = origin

    inconsistent_run_snapshots: list[dict[str, Any]] = []
    if _table_exists(connection, "runs") and _table_exists(connection, "catalogue_snapshots"):
        rows = connection.execute(sa.text(
            "SELECT r.run_id, r.project_path, c.project_path "
            "FROM runs r JOIN catalogue_snapshots c ON c.id = r.catalogue_snapshot_id"
        ))
        for run_id, run_path, snapshot_path in rows:
            if path_targets.get(str(run_path)) != path_targets.get(str(snapshot_path)):
                inconsistent_run_snapshots.append({
                    "run_id": str(run_id),
                    "run_project_path": str(run_path),
                    "snapshot_project_path": str(snapshot_path),
                })

    conflicting_current_mappings: list[dict[str, Any]] = []
    if _table_exists(connection, "compliance_mappings"):
        counts: dict[str, list[int]] = {}
        for mapping_id, project_path in connection.execute(sa.text(
            "SELECT id, project_path FROM compliance_mappings ORDER BY id"
        )):
            mapping_target = path_targets.get(str(project_path))
            if mapping_target:
                counts.setdefault(mapping_target, []).append(int(mapping_id))
        conflicting_current_mappings = [
            {"target": target, "mapping_ids": ids}
            for target, ids in sorted(counts.items())
            if len(ids) > 1
        ]

    duplicate_scanner_runs: list[dict[str, Any]] = []
    if _table_exists(connection, "scanner_runs"):
        duplicate_scanner_runs = [
            {"run_id": str(run_id), "scanner_kind": str(kind), "count": int(count)}
            for run_id, kind, count in connection.execute(sa.text(
                "SELECT run_id, scanner_kind, count(*) FROM scanner_runs "
                "GROUP BY run_id, scanner_kind HAVING count(*) > 1"
            ))
        ]

    created = [
        {"repository": creation.repository, "repository_key": creation.repository_key, "tag": creation.tag}
        for creation in sorted(creations_by_key.values(), key=lambda item: item.repository_key)
    ]
    blockers = {
        "invalid_projects": invalid_projects,
        "ambiguous_repository_keys": ambiguous_repository_keys,
        "ambiguous_paths": ambiguous,
        "unresolved_paths": unresolved,
        "tombstoned_paths": tombstoned,
        "unresolved_checkouts": unresolved_checkouts,
        "invalid_runs": invalid_runs,
        "inconsistent_run_snapshots": inconsistent_run_snapshots,
        "conflicting_current_mappings": conflicting_current_mappings,
        "duplicate_scanner_runs": duplicate_scanner_runs,
        "duplicate_repository_ids": duplicate_repository_ids,
    }
    report: dict[str, Any] = {
        "schema": "assurance-scan-identity-preflight-v1",
        "matched": matched,
        "created": created,
        "blockers": blockers,
        "summary": {
            "legacy_identity_count": len(paths),
            "matched_count": len(matched),
            "created_count": len(created),
            "blocker_count": sum(len(items) for items in blockers.values()),
        },
    }
    if report["summary"]["blocker_count"]:
        raise IdentityPreflightError(report)
    return IdentityPlan(
        path_targets=path_targets,
        projects_to_create=tuple(sorted(creations_by_key.values(), key=lambda item: item.repository_key)),
        checkout_users=checkout_users,
        run_origins=run_origins,
        report=report,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Report whether a SQLite DB can undergo migration 0021")
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    engine = sa.create_engine(f"sqlite:///{args.database.resolve()}")
    try:
        with engine.connect() as connection:
            try:
                plan = build_identity_plan(connection)
            except IdentityPreflightError as exc:
                print(json.dumps(exc.report, indent=2, sort_keys=True))
                return 2
        print(json.dumps(plan.report, indent=2, sort_keys=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
