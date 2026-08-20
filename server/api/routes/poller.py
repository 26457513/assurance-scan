"""On-demand poll trigger — the scans-page "refresh from GitHub" button."""
from __future__ import annotations

from typing import Any

import asyncio

from fastapi import APIRouter, Request

from server.db.connection import get_sessionmaker
from server.github_poller import poll_all_orgs


router = APIRouter(prefix="/poller", tags=["poller"])


@router.post("/poll-now")
async def poll_now(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.github_poll_token:
        return {
            "error": "poller not configured",
            "hint": "set GITHUB_POLL_TOKEN (and GITHUB_ORG or POLL_REPOS) on the server",
        }
    return await poll_all_orgs(
        get_sessionmaker(settings), settings.github_poll_token, settings.github_org
    )
