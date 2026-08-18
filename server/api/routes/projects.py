"""Projects endpoint — the project registry derived from runs + snapshots."""
from __future__ import annotations

from pathlib import PurePath
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import CatalogueSnapshot, Project, Run


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


@router.post("")
async def create_project(
    request: Request,
    session: AsyncSession = SessionDep,
    tag: str = Body(...),
    local_path: str = Body(...),
    github_url: str = Body(default=""),
) -> dict[str, Any]:
    """Register a project: tag + full local path + optional GitHub repo URL.

    The repo may be a full URL (https://github.com/org/repo[.git]) or a
    bare `org/repo`. The org key in .env provides GitHub access.
    """
    import os as _os

    tag = tag.strip()
    local_path = _os.path.expanduser(local_path.strip())
    if not tag or not local_path:
        raise HTTPException(status_code=400, detail="tag and local_path are required")
    if not _os.path.isdir(local_path):
        raise HTTPException(status_code=422, detail=f"local path not found on this machine: {local_path}")

    repo = _parse_github_repo(github_url.strip())
    from sqlalchemy import select as _select

    existing = (
        await session.execute(
            _select(Project).where((Project.tag == tag) | (Project.local_path == local_path))
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="a project with this tag or local path already exists")

    project = Project(tag=tag, local_path=local_path, github_repo=repo)
    session.add(project)
    await session.commit()
    return {"status": "created", "tag": tag, "local_path": local_path, "github_repo": repo}


def _parse_github_repo(url: str) -> str | None:
    """https://github.com/org/repo(.git)/ or org/repo -> org/repo."""
    if not url:
        return None
    cleaned = url.strip().rstrip("/").removesuffix(".git")
    if cleaned.startswith("http"):
        parts = [p for p in cleaned.split("/") if p]
        if len(parts) >= 2 and "github.com" in parts:
            if parts[-2] == "github.com":
                return "/".join(parts[-2:])
        if "github.com" in cleaned:
            idx = parts.index("github.com")
            if len(parts) >= idx + 3:
                return f"{parts[idx + 1]}/{parts[idx + 2]}"
        raise HTTPException(status_code=422, detail=f"not a github repo URL: {url}")
    if cleaned.count("/") == 1:
        return cleaned
    raise HTTPException(status_code=422, detail=f"expected org/repo or a github URL: {url}")


class ProjectUpdate(BaseModel):
    tag: str | None = None
    local_path: str | None = None
    github_url: str | None = None


@router.patch("/{project_id}")
async def update_project(
    project_id: int,
    update: ProjectUpdate,
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Edit a registered project: tag, local path, and/or GitHub repo.

    An empty github_url clears the repo link; tag/local_path must be
    non-empty when provided. Validated like creation.
    """
    import os as _os
    from sqlalchemy import select as _select

    tag = update.tag
    local_path = update.local_path
    github_url = update.github_url

    project = (
        await session.execute(_select(Project).where(Project.id == project_id))
    ).scalars().first()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if tag is not None:
        tag = tag.strip()
        if not tag:
            raise HTTPException(status_code=400, detail="tag cannot be empty")
        project.tag = tag
    if local_path is not None:
        local_path = _os.path.expanduser(local_path.strip())
        if not local_path:
            raise HTTPException(status_code=400, detail="local_path cannot be empty")
        if not _os.path.isdir(local_path):
            raise HTTPException(status_code=422, detail=f"local path not found on this machine: {local_path}")
        project.local_path = local_path
    if github_url is not None:
        project.github_repo = _parse_github_repo(github_url.strip())

    clash = (
        await session.execute(
            _select(Project).where(
                ((Project.tag == project.tag) | (Project.local_path == project.local_path))
                & (Project.id != project.id)
            )
        )
    ).scalars().first()
    if clash is not None:
        raise HTTPException(status_code=409, detail="another project already uses this tag or local path")

    await session.commit()
    return {
        "status": "updated",
        "tag": project.tag,
        "local_path": project.local_path,
        "github_repo": project.github_repo,
    }


@router.get("")
async def list_projects(request: Request, session: AsyncSession = SessionDep) -> dict[str, Any]:
    """Registered projects first (explicit identity), then derived leftovers."""
    run_rows = (
        await session.execute(
            sa_select(
                Run.project_path,
                func.count(Run.run_id).label("run_count"),
                func.max(Run.started_at).label("last_scan_at"),
            ).group_by(Run.project_path)
        )
    ).all()
    run_stats = {r.project_path: r for r in run_rows}

    catalogue_rows = (
        await session.execute(
            sa_select(
                CatalogueSnapshot.project_path,
                func.max(CatalogueSnapshot.created_at).label("latest_snapshot_at"),
            ).group_by(CatalogueSnapshot.project_path)
        )
    ).all()
    catalogue_by_project = {r.project_path: r.latest_snapshot_at for r in catalogue_rows}

    def stats_for(identities: list[str]) -> dict[str, Any]:
        counts = [run_stats[i].run_count for i in identities if i in run_stats]
        lasts = [run_stats[i].last_scan_at for i in identities if i in run_stats]
        return {
            "run_count": sum(counts),
            "last_scan_at": max(lasts).isoformat() if lasts else None,
            "has_catalogue": any(i in catalogue_by_project for i in identities),
        }

    registry = (await session.execute(sa_select(Project).order_by(Project.tag))).scalars().all()
    projects: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for reg in registry:
        identities = [reg.local_path]
        gh = f"github:{reg.github_repo}" if reg.github_repo else None
        if gh:
            identities.append(gh)
        consumed.update(identities)
        projects.append({
            "id": reg.id,
            "project_path": reg.local_path,
            "tag": reg.tag,
            "github_project": gh,
            "registered": True,
            **stats_for(identities),
        })

    # Derived rows for identities no registered project claims.
    leftovers = [
        {
            "project_path": path,
            "run_count": r.run_count,
            "last_scan_at": r.last_scan_at.isoformat() if r.last_scan_at else None,
            "has_catalogue": path in catalogue_by_project,
        }
        for path, r in run_stats.items()
        if path not in consumed
    ]
    for path in catalogue_by_project:
        if path not in run_stats and path not in consumed:
            leftovers.append({
                "project_path": path, "run_count": 0, "last_scan_at": None, "has_catalogue": True,
            })

    org = request.app.state.settings.github_org
    leftovers = merge_github_aliases(leftovers, org)
    projects.extend(leftovers)
    projects.sort(key=lambda p: p["last_scan_at"] or "", reverse=True)
    return {"projects": projects}
