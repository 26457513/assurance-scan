"""GitHub org repos + source peek for the CI-centric UI (phase 3)."""
from __future__ import annotations

import asyncio
import base64
import functools
import urllib.error
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from server.github_poller import GitHubClient


router = APIRouter(prefix="/github", tags=["github"])

MAX_PEEK_BYTES = 1_000_000
CONTEXT_PAD = 3  # lines above/below the flagged line


@router.get("/repos")
async def list_repos(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.github_poll_token or not settings.github_org:
        return {"org": settings.github_org, "repos": []}
    client = GitHubClient(settings.github_poll_token)
    try:
        repos = await asyncio.to_thread(client.org_repos, settings.github_org)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub listing failed: {exc}") from exc
    return {
        "org": settings.github_org,
        "repos": [
            {
                "full_name": r["full_name"],
                "name": r.get("name"),
                "pushed_at": r.get("pushed_at"),
                "html_url": r.get("html_url"),
            }
            for r in repos
        ]
    }


def _window(lines: list[str], line: int | None, pad: int = CONTEXT_PAD) -> dict[str, Any]:
    """1-indexed `line` plus `pad` lines either side."""
    if line is None or line < 1:
        line = 1
    start = max(1, line - pad)
    end = min(len(lines), line + pad)
    return {
        "start_line": start,
        "end_line": end,
        "highlight": min(line, max(len(lines), 1)),
        "lines": [
            {"n": n, "text": lines[n - 1]} for n in range(start, end + 1)
        ],
    }


@functools.lru_cache(maxsize=128)
def _fetch_file(token: str, repo: str, commit: str, path: str) -> str | None:
    """Raw text or None when unavailable (missing, binary, too large).

    None results are cached too — a missing file at an immutable sha stays
    missing, and repeat peeks shouldn't hammer the API.
    """
    client = GitHubClient(token)
    try:
        raw = client.file_contents(repo, commit, path)
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None
    if len(raw) > MAX_PEEK_BYTES or b"\0" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="replace")


@router.get("/source")
async def source_peek(
    request: Request,
    repo: str,
    commit: str,
    path: str,
    line: int | None = None,
) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.github_poll_token:
        raise HTTPException(status_code=503, detail="GitHub token not configured")
    text = await asyncio.to_thread(
        _fetch_file, settings.github_poll_token, repo, commit, path
    )
    if text is None:
        return {"unavailable": True, "path": path}
    return _window(text.splitlines(), line)
