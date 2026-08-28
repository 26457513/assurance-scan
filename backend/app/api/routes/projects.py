"""Registered projects addressed exclusively by durable numeric identity."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.infrastructure.db.models import (
    CatalogueSnapshot,
    ComplianceMapping,
    ComplianceMappingSnapshot,
    FindingAcceptance,
    Project,
    Run,
    Waiver,
)
from app.modules.atomic.provenance.repository_identity import (
    InvalidRepositoryIdentityError,
    normalize_github_repository_key,
    parse_github_repository,
)


router = APIRouter(prefix="/projects", tags=["projects"])


def _parse_github_repo(value: str) -> str | None:
    try:
        return parse_github_repository(value)
    except InvalidRepositoryIdentityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _project_payload(project: Project, **statistics: Any) -> dict[str, Any]:
    return {
        "id": project.id,
        "tag": project.tag,
        "local_path": project.local_path,
        "github_repo": project.github_repo,
        "github_repository_id": project.github_repository_id,
        "default_scan_ref": project.default_scan_ref,
        **statistics,
    }


async def _find_conflict(
    session: AsyncSession,
    *,
    tag: str,
    local_path: str | None,
    github_repo_key: str | None,
    excluding_id: int | None = None,
) -> Project | None:
    clauses = [Project.tag == tag]
    if local_path is not None:
        clauses.append(Project.local_path == local_path)
    if github_repo_key is not None:
        clauses.append(Project.github_repo_key == github_repo_key)
    statement = select(Project).where(or_(*clauses))
    if excluding_id is not None:
        statement = statement.where(Project.id != excluding_id)
    return (await session.execute(statement)).scalars().first()


@router.post("")
async def create_project(
    session: AsyncSession = SessionDep,
    tag: str = Body(...),
    local_path: str | None = Body(default=None),
    github_repo: str | None = Body(default=None),
    default_scan_ref: str | None = Body(default=None),
) -> dict[str, Any]:
    """Register one durable project with a local and/or GitHub locator."""
    normalized_tag = tag.strip()
    normalized_path = os.path.expanduser((local_path or "").strip()) or None
    raw_url = (github_repo or "").strip()
    default_scan_ref = (default_scan_ref or "").strip() or None
    repository = _parse_github_repo(raw_url)
    repository_key = (
        normalize_github_repository_key(repository) if repository is not None else None
    )
    if not normalized_tag:
        raise HTTPException(status_code=400, detail="tag is required")
    if normalized_path is None and repository is None:
        raise HTTPException(
            status_code=400,
            detail="local_path or a GitHub repository is required",
        )
    if normalized_path is not None and not os.path.isdir(normalized_path):
        raise HTTPException(
            status_code=422,
            detail=f"local path not found on this machine: {normalized_path}",
        )
    conflict = await _find_conflict(
        session,
        tag=normalized_tag,
        local_path=normalized_path,
        github_repo_key=repository_key,
    )
    if conflict is not None:
        raise HTTPException(status_code=409, detail="project identity already registered")

    project = Project(
        tag=normalized_tag,
        local_path=normalized_path,
        github_repo=repository,
        github_repo_key=repository_key,
        default_scan_ref=default_scan_ref,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return {"status": "created", **_project_payload(project)}


class ProjectUpdate(BaseModel):
    tag: str | None = None
    local_path: str | None = None
    github_repo: str | None = None
    default_scan_ref: str | None = None


@router.patch("/{project_id}")
async def update_project(
    project_id: int,
    update: ProjectUpdate,
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Update locators without changing the project's durable identity."""
    project = await session.get(Project, project_id)
    if project is None or project.hidden:
        raise HTTPException(status_code=404, detail="project not found")

    tag = project.tag
    local_path = project.local_path
    github_repo = project.github_repo
    github_repo_key = project.github_repo_key
    if update.tag is not None:
        tag = update.tag.strip()
        if not tag:
            raise HTTPException(status_code=400, detail="tag cannot be empty")
    if "local_path" in update.model_fields_set:
        local_path = os.path.expanduser((update.local_path or "").strip()) or None
        if local_path is not None and not os.path.isdir(local_path):
            raise HTTPException(
                status_code=422,
                detail=f"local path not found on this machine: {local_path}",
            )
    if "github_repo" in update.model_fields_set:
        github_repo = _parse_github_repo((update.github_repo or "").strip())
        github_repo_key = (
            normalize_github_repository_key(github_repo)
            if github_repo is not None
            else None
        )
    if local_path is None and github_repo_key is None:
        raise HTTPException(
            status_code=400,
            detail="project must retain a local path or GitHub repository",
        )
    if await _find_conflict(
        session,
        tag=tag,
        local_path=local_path,
        github_repo_key=github_repo_key,
        excluding_id=project.id,
    ) is not None:
        raise HTTPException(status_code=409, detail="project identity already registered")

    project.tag = tag
    project.local_path = local_path
    project.github_repo = github_repo
    project.github_repo_key = github_repo_key
    if update.default_scan_ref is not None:
        project.default_scan_ref = update.default_scan_ref.strip() or None
    await session.commit()
    return {"status": "updated", **_project_payload(project)}


@router.delete("/{project_id}")
async def delete_project(
    project_id: int, session: AsyncSession = SessionDep
) -> dict[str, Any]:
    """Delete project-owned scan data and retain an identity tombstone."""
    project = await session.get(Project, project_id)
    if project is None or project.hidden:
        raise HTTPException(status_code=404, detail="project not found")

    from app.infrastructure.db.retention import prepare_runs_for_deletion

    run_ids = tuple(
        (await session.execute(select(Run.run_id).where(Run.project_id == project_id))).scalars()
    )
    await prepare_runs_for_deletion(session, run_ids)
    await session.execute(delete(Run).where(Run.project_id == project_id))
    for model in (
        CatalogueSnapshot,
        ComplianceMapping,
        ComplianceMappingSnapshot,
        FindingAcceptance,
        Waiver,
    ):
        await session.execute(delete(model).where(model.project_id == project_id))
    project.hidden = True
    await session.commit()
    return {"status": "deleted", "id": project.id, "tag": project.tag}


@router.get("")
async def list_projects(session: AsyncSession = SessionDep) -> dict[str, Any]:
    """List visible registered projects; derived path identities do not exist."""
    run_statistics = (
        select(
            Run.project_id.label("project_id"),
            func.count(Run.run_id).label("run_count"),
            func.max(Run.started_at).label("last_scan_at"),
        )
        .group_by(Run.project_id)
        .subquery()
    )
    catalogue_projects = (
        select(CatalogueSnapshot.project_id.label("project_id"))
        .group_by(CatalogueSnapshot.project_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Project,
                run_statistics.c.run_count,
                run_statistics.c.last_scan_at,
                catalogue_projects.c.project_id.label("catalogue_project_id"),
            )
            .outerjoin(run_statistics, run_statistics.c.project_id == Project.id)
            .outerjoin(catalogue_projects, catalogue_projects.c.project_id == Project.id)
            .where(Project.hidden.is_(False))
            .order_by(run_statistics.c.last_scan_at.desc(), Project.tag)
        )
    ).all()
    return {
        "projects": [
            _project_payload(
                project,
                run_count=int(run_count or 0),
                last_scan_at=last_scan_at.isoformat() if last_scan_at else None,
                has_catalogue=catalogue_project_id is not None,
            )
            for project, run_count, last_scan_at, catalogue_project_id in rows
        ]
    }
