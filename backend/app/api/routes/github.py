"""GitHub repository discovery for the CI-centric UI."""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Request

from app.api.deps import SessionDep
from app.api.deps_project_access import ProjectAccessDep
from app.github_poller import GitHubClient, resolve_registered_repository
from app.infrastructure.project_access import require_project


router = APIRouter(prefix="/github", tags=["github"])

@router.get("/repos")
async def list_repos(
    request: Request,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """All repos visible across the home org and every registered org."""
    from sqlalchemy import select as sa_select

    from app.infrastructure.db.models import Organisation
    from app.secrets import decrypt

    settings = request.app.state.settings
    if not principal.sees_all_projects:
        from sqlalchemy import select as _select

        from app.infrastructure.db.models import Project
        from app.infrastructure.project_access import project_access_clause

        projects = (
            await session.execute(
                _select(Project)
                .where(
                    project_access_clause(principal),
                    Project.github_repo.is_not(None),
                )
                .order_by(Project.github_repo)
            )
        ).scalars().all()
        return {
            "org": settings.github_org,
            "repos": [
                {
                    "id": project.github_repository_id,
                    "full_name": project.github_repo,
                    "name": (project.github_repo or "").rsplit("/", 1)[-1],
                    "org": (project.github_repo or "").split("/", 1)[0],
                    "pushed_at": None,
                    "html_url": f"https://github.com/{project.github_repo}",
                    "project_id": project.id,
                    "registration": "registered",
                }
                for project in projects
            ],
            "errors": [],
        }
    org_tokens: list[tuple[str, str]] = []
    if settings.github_poll_token and settings.github_org:
        org_tokens.append((settings.github_org, settings.github_poll_token))
    if settings.token_encryption_key:
        rows = (await session.execute(sa_select(Organisation))).scalars().all()
        for row in rows:
            token = decrypt(row.token_encrypted, settings.token_encryption_key)
            if token:
                org_tokens.append((row.name, token))

    repos: list[dict[str, Any]] = []
    errors: list[str] = []
    for org, token in org_tokens:
        try:
            listed = await asyncio.to_thread(GitHubClient(token).org_repos, org)
        except Exception as exc:
            errors.append(f"{org}: {exc}")
            continue
        for repository in listed:
            try:
                full_name, repository_id, project_id, resolution = (
                    await resolve_registered_repository(session, repository)
                )
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{org}: invalid repository identity ({exc})")
                continue
            repos.append({
                "id": repository_id,
                "full_name": full_name,
                "name": full_name.rsplit("/", 1)[-1],
                "org": org,
                "pushed_at": repository.get("pushed_at"),
                "html_url": repository.get("html_url"),
                "project_id": project_id,
                "registration": resolution,
            })
    repos.sort(key=lambda r: r["full_name"])
    return {"org": settings.github_org, "repos": repos, "errors": errors}


@router.get("/branches")
async def list_branches(
    request: Request,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
    repo: str = "",
) -> dict[str, Any]:
    """Branches of a repo, resolved with the same token chain as dispatch."""
    from app.api.routes.gh_tokens import resolve_repo_token
    from fastapi import HTTPException as _HTTP

    if not repo:
        raise _HTTP(status_code=400, detail="repo required")
    from app.infrastructure.db.models import Project
    from app.modules.atomic.provenance.repository_identity import normalize_github_repository_key
    from sqlalchemy import select as _select

    project = (
        await session.execute(
            _select(Project).where(
                Project.github_repo_key == normalize_github_repository_key(repo)
            )
        )
    ).scalar_one_or_none()
    if project is None or await require_project(session, principal, project.id) is None:
        raise _HTTP(status_code=404, detail="project not found")
    token, source = await resolve_repo_token(request, session, repo)
    if not token:
        raise _HTTP(status_code=422, detail="no credential can read this repo")
    try:
        branches = await asyncio.to_thread(GitHubClient(token).repo_branches, repo)
    except Exception as exc:
        raise _HTTP(status_code=422, detail=f"cannot read branches ({source}): {exc}")
    return {"repo": repo, "branches": branches}
