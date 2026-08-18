"""On-demand poll trigger — the scans-page "refresh from GitHub" button."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from server.db.connection import get_sessionmaker
from server.github_poller import GitHubClient, poll_cycle


router = APIRouter(prefix="/poller", tags=["poller"])


@router.post("/poll-now")
async def poll_now(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.github_poll_token or not settings.poll_repos:
        return {
            "error": "poller not configured",
            "hint": "set GITHUB_POLL_TOKEN and POLL_REPOS on the server",
        }
    client = GitHubClient(settings.github_poll_token)
    result = await poll_cycle(get_sessionmaker(settings), client, settings.poll_repos)
    return result
