"""GitHub org repos + source peek for the CI-centric UI (phase 3)."""
from __future__ import annotations

import asyncio
import base64
import functools
import urllib.error
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, HTTPException, Request

from server.api.deps import SessionDep
from server.github_poller import GitHubClient


router = APIRouter(prefix="/github", tags=["github"])

MAX_PEEK_BYTES = 1_000_000
CONTEXT_PAD = 3  # lines above/below the flagged line


@router.get("/repos")
async def list_repos(request: Request, session: AsyncSession = SessionDep) -> dict[str, Any]:
    """All repos visible across the home org and every registered org."""
    from sqlalchemy import select as sa_select

    from server.db.models import Organisation
    from server.secrets import decrypt

    settings = request.app.state.settings
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
        repos.extend({
            "full_name": r["full_name"],
            "name": r.get("name"),
            "org": org,
            "pushed_at": r.get("pushed_at"),
            "html_url": r.get("html_url"),
        } for r in listed)
    repos.sort(key=lambda r: r["full_name"])
    return {"org": settings.github_org, "repos": repos, "errors": errors}


@router.get("/branches")
async def list_branches(
    request: Request, session: AsyncSession = SessionDep, repo: str = ""
) -> dict[str, Any]:
    """Branches of a repo, resolved with the same token chain as dispatch."""
    from server.api.routes.gh_tokens import resolve_repo_token
    from fastapi import HTTPException as _HTTP

    if not repo:
        raise _HTTP(status_code=400, detail="repo required")
    token, source = await resolve_repo_token(request, session, repo)
    if not token:
        raise _HTTP(status_code=422, detail="no credential can read this repo")
    try:
        branches = await asyncio.to_thread(GitHubClient(token).repo_branches, repo)
    except Exception as exc:
        raise _HTTP(status_code=422, detail=f"cannot read branches ({source}): {exc}")
    return {"repo": repo, "branches": branches}


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
