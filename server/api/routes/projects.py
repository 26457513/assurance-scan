"""Projects endpoint — the project registry derived from runs + snapshots."""
from __future__ import annotations

from pathlib import PurePath
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import CatalogueSnapshot, Run


router = APIRouter(prefix="/projects", tags=["projects"])


def merge_github_aliases(projects: list[dict[str, Any]], org: str) -> list[dict[str, Any]]:
    """Fold `github:{org}/{name}` projects into the local project whose
    folder name matches (`…/{name}`). Path-derived by convention; a local
    project with no matching repo keeps its own row and vice versa."""
    if not org:
        return projects
    by_path = {p["project_path"]: p for p in projects}
    merged: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for p in projects:
        path = p["project_path"]
        if path.startswith("github:") or path in consumed:
            continue
        alias = f"github:{org}/{PurePath(path).name}"
        gh = by_path.get(alias)
        row = dict(p)
        if gh is not None:
            consumed.add(alias)
            row["github_project"] = alias
            row["run_count"] = p["run_count"] + gh["run_count"]
            row["last_scan_at"] = max(
                filter(None, [p["last_scan_at"], gh["last_scan_at"]]), default=None
            )
            row["has_catalogue"] = p["has_catalogue"] or gh["has_catalogue"]
        merged.append(row)
    for p in projects:
        if p["project_path"] not in consumed and not p["project_path"].startswith("github:"):
            continue
        if p["project_path"] in consumed:
            continue
        merged.append(p)
    return merged


@router.get("")
async def list_projects(request: Request, session: AsyncSession = SessionDep) -> dict[str, Any]:
    """Distinct project paths with run counts, latest scan time, and catalogue info."""
    run_rows = (
        await session.execute(
            sa_select(
                Run.project_path,
                func.count(Run.run_id).label("run_count"),
                func.max(Run.started_at).label("last_scan_at"),
            ).group_by(Run.project_path)
        )
    ).all()

    catalogue_rows = (
        await session.execute(
            sa_select(
                CatalogueSnapshot.project_path,
                func.max(CatalogueSnapshot.created_at).label("latest_snapshot_at"),
            ).group_by(CatalogueSnapshot.project_path)
        )
    ).all()
    catalogue_by_project = {r.project_path: r.latest_snapshot_at for r in catalogue_rows}

    projects = [
        {
            "project_path": r.project_path,
            "run_count": r.run_count,
            "last_scan_at": r.last_scan_at.isoformat() if r.last_scan_at else None,
            "has_catalogue": r.project_path in catalogue_by_project,
        }
        for r in run_rows
    ]
    # Projects with a catalogue but no runs yet still belong in the registry.
    known = {r.project_path for r in run_rows}
    for path, latest in catalogue_by_project.items():
        if path not in known:
            projects.append(
                {
                    "project_path": path,
                    "run_count": 0,
                    "last_scan_at": None,
                    "has_catalogue": True,
                }
            )

    org = request.app.state.settings.github_org
    projects = merge_github_aliases(projects, org)
    projects.sort(key=lambda p: p["last_scan_at"] or "", reverse=True)
    return {"projects": projects}
