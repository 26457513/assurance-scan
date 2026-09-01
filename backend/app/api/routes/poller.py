"""On-demand poll trigger — the scans-page "refresh from GitHub" button."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps_project_access import ProjectAccessDep
from app.infrastructure.db.connection import get_sessionmaker
from app.github_poller import poll_all_orgs


router = APIRouter(prefix="/poller", tags=["poller"])


@router.post("/poll-now")
async def poll_now(request: Request, principal: ProjectAccessDep) -> dict[str, Any]:
    if not principal.sees_all_projects:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="polling requires an administrator")
    settings = request.app.state.settings
    if not settings.github_poll_token:
        return {
            "error": "poller not configured",
            "hint": "set GITHUB_POLL_TOKEN (and GITHUB_ORG or POLL_REPOS) on the server",
        }
    return await poll_all_orgs(
        get_sessionmaker(settings), settings.github_poll_token, settings.github_org
    )
