"""Deterministic repository identity transformations."""

from __future__ import annotations

from pathlib import PurePath
from typing import cast

from .models import InvalidRepositoryIdentityError, ProjectSummary


def parse_github_repository(value: str) -> str | None:
    """Return ``owner/repository`` for an existing supported input form.

    This deliberately retains the project registry's pre-refactor parsing
    contract. Broader remote forms and stricter canonicalisation belong to the
    local-scan feature work, not this behavior-preserving extraction.
    """
    if not value:
        return None
    cleaned = value.strip().rstrip("/").removesuffix(".git")
    if cleaned.startswith("http"):
        parts = [part for part in cleaned.split("/") if part]
        if len(parts) >= 2 and "github.com" in parts:
            if parts[-2] == "github.com":
                return "/".join(parts[-2:])
        if "github.com" in cleaned:
            try:
                index = parts.index("github.com")
            except ValueError as exc:
                raise InvalidRepositoryIdentityError(
                    f"not a github repo URL: {value}"
                ) from exc
            if len(parts) >= index + 3:
                return f"{parts[index + 1]}/{parts[index + 2]}"
        raise InvalidRepositoryIdentityError(f"not a github repo URL: {value}")
    if cleaned.count("/") == 1:
        return cleaned
    raise InvalidRepositoryIdentityError(
        f"expected org/repo or a github URL: {value}"
    )


def merge_github_aliases(
    projects: list[ProjectSummary], org: str
) -> list[ProjectSummary]:
    """Fold an organisation's GitHub row into its matching local folder row.

    Matching remains basename-based for compatibility. Durable registered
    project identity will replace this fallback in the local-scan workstream.
    """
    if not org:
        return projects
    by_path = {project["project_path"]: project for project in projects}
    merged: list[ProjectSummary] = []
    consumed: set[str] = set()
    for project in projects:
        path = project["project_path"]
        if path.startswith("github:") or path in consumed:
            continue
        alias = f"github:{org}/{PurePath(path).name}"
        github_project = by_path.get(alias)
        row = dict(project)
        if github_project is not None:
            consumed.add(alias)
            row["github_project"] = alias
            row["run_count"] = project["run_count"] + github_project["run_count"]
            row["last_scan_at"] = max(
                filter(
                    None,
                    [project["last_scan_at"], github_project["last_scan_at"]],
                ),
                default=None,
            )
            row["has_catalogue"] = (
                project["has_catalogue"] or github_project["has_catalogue"]
            )
        merged.append(cast(ProjectSummary, row))
    for project in projects:
        path = project["project_path"]
        if path not in consumed and not path.startswith("github:"):
            continue
        if path in consumed:
            continue
        merged.append(project)
    return merged
