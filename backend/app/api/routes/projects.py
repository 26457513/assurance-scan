"""Projects endpoint — the project registry derived from runs + snapshots."""
from __future__ import annotations

from pathlib import PurePath
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.infrastructure.db.models import (
    CatalogueSnapshot,
    ComplianceMapping,
    ComplianceMappingSnapshot,
    Project,
    Run,
)
from app.modules.atomic.provenance.repository_identity import (
    InvalidRepositoryIdentityError,
    merge_github_aliases as _merge_github_aliases,
    parse_github_repository,
)


router = APIRouter(prefix="/projects", tags=["projects"])


def merge_github_aliases(projects: list[dict[str, Any]], org: str) -> list[dict[str, Any]]:
    """Compatibility wrapper for the atomic alias reconciliation service."""
    return _merge_github_aliases(projects, org)  # type: ignore[arg-type,return-value]


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
    raw_url = github_url.strip()
    default_scan_ref = ""
    if "#" in raw_url:
        raw_url, default_scan_ref = raw_url.split("#", 1)
        default_scan_ref = default_scan_ref.strip()
    repo = _parse_github_repo(raw_url)
    if not tag:
        raise HTTPException(status_code=400, detail="tag is required")
    if not local_path and not repo:
        raise HTTPException(status_code=400, detail="local_path or a GitHub repo URL is required")
    if local_path and not repo and not _os.path.isdir(local_path):
        raise HTTPException(status_code=422, detail=f"local path not found on this machine: {local_path}")
    # GitHub-only projects anchor on the scan identity itself.
    anchor = local_path if local_path else f"github:{repo}"
    from sqlalchemy import select as _select

    existing = (
        await session.execute(
            _select(Project).where((Project.tag == tag) | (Project.local_path == anchor))
        )
    ).scalars().first()
    if existing is not None and not existing.hidden:
        raise HTTPException(status_code=409, detail="a project with this tag or local path already exists")
    if existing is not None:
        # Re-registering a deleted (tombstoned) project revives it.
        existing.hidden = False
        existing.tag = tag
        existing.github_repo = repo
        await session.commit()
        return {
            "status": "registered",
            "tag": existing.tag,
            "local_path": existing.local_path,
            "github_repo": existing.github_repo,
        }

    project = Project(tag=tag, local_path=anchor, github_repo=repo,
                      default_scan_ref=default_scan_ref or None)
    session.add(project)
    await session.commit()
    return {"status": "created", "tag": tag, "local_path": anchor, "github_repo": repo, "default_scan_ref": default_scan_ref or None}


def _parse_github_repo(url: str) -> str | None:
    """Compatibility adapter preserving the route's HTTP error contract."""
    try:
        return parse_github_repository(url)
    except InvalidRepositoryIdentityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class ProjectUpdate(BaseModel):
    tag: str | None = None
    local_path: str | None = None
    github_url: str | None = None
    default_scan_ref: str | None = None


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

    if update.default_scan_ref is not None:
        project.default_scan_ref = update.default_scan_ref or None

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


@router.delete("/{project_id}")
async def delete_project(project_id: int, session: AsyncSession = SessionDep) -> dict[str, Any]:
    """Remove a project and everything it produced locally.

    GitHub is untouched; local runs, findings, FR catalogues and compliance
    mappings for every identity of the project are deleted (child rows go
    via FK cascades). Without this the list rebuilds the row from its runs.
    """
    from sqlalchemy import delete as sa_delete

    project = (
        await session.execute(sa_select(Project).where(Project.id == project_id))
    ).scalars().first()
    if project is None or project.hidden:
        raise HTTPException(status_code=404, detail="project not found")
    identities = {project.local_path}
    if project.github_repo:
        identities.add(f"github:{project.github_repo}")

    for run in (
        await session.execute(sa_select(Run).where(Run.project_path.in_(identities)))
    ).scalars().all():
        await session.delete(run)
    await session.execute(
        sa_delete(CatalogueSnapshot).where(CatalogueSnapshot.project_path.in_(identities))
    )
    await session.execute(
        sa_delete(ComplianceMappingSnapshot).where(
            ComplianceMappingSnapshot.project_path.in_(identities)
        )
    )
    await session.execute(
        sa_delete(ComplianceMapping).where(ComplianceMapping.project_path.in_(identities))
    )
    # Tombstone: keep the row hidden so the org-repos merge and the poller
    # don't resurrect the project on the next cycle.
    project.hidden = True
    await session.commit()
    return {"status": "deleted", "tag": project.tag}


class HideBody(BaseModel):
    project_path: str


@router.post("/hide")
async def hide_project(body: HideBody, session: AsyncSession = SessionDep) -> dict[str, Any]:
    """Tombstone an unregistered project path (no registry row to delete)."""
    path = body.project_path.strip()
    if not path:
        raise HTTPException(status_code=400, detail="project_path required")
    existing = (
        await session.execute(sa_select(Project).where(Project.local_path == path))
    ).scalars().first()
    if existing is not None:
        existing.hidden = True
    else:
        session.add(Project(
            tag=PurePath(path.replace("github:", "")).name or path,
            local_path=path,
            github_repo=path[7:] if path.startswith("github:") else None,
            hidden=True,
        ))
    await session.commit()
    return {"status": "hidden", "project_path": path}


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
    excluded: set[str] = set()
    for reg in registry:
        identities = [reg.local_path]
        gh = f"github:{reg.github_repo}" if reg.github_repo else None
        if gh:
            identities.append(gh)
        consumed.update(identities)
        if reg.hidden:
            # Tombstoned — not listed, and its identities don't resurface
            # as leftovers or via the frontend's org-repos merge.
            excluded.update(identities)
            continue
        projects.append({
            "id": reg.id,
            "project_path": reg.local_path,
            "tag": reg.tag,
            "default_scan_ref": reg.default_scan_ref,
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
    leftovers = [p for p in leftovers if p["project_path"] not in excluded]
    projects.extend(leftovers)
    projects.sort(key=lambda p: p["last_scan_at"] or "", reverse=True)
    return {"projects": projects, "excluded": sorted(excluded)}
