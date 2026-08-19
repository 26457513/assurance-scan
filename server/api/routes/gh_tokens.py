"""Per-user GitHub tokens + remote scan dispatch + runner tarball proxy."""
from __future__ import annotations

import urllib.parse
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import GithubAccount
from server.github_poller import GitHubClient
from server.secrets import decrypt, encrypt


router = APIRouter(tags=["github"])


def _user_email(request: Request) -> str | None:
    """From the Google session cookie (HMAC-signed)."""
    from server.auth import verify_session

    settings = request.app.state.settings
    if not settings.session_secret:
        return None
    return verify_session(request.cookies.get("as_session"), settings.session_secret)


async def resolve_user_token(request: Request, session: AsyncSession) -> tuple[str | None, str | None]:
    """(token, login) for the signed-in user, else (None, None)."""
    email = _user_email(request)
    if not email:
        return None, None
    row = (
        await session.execute(sa_select(GithubAccount).where(GithubAccount.email == email))
    ).scalars().first()
    if row is None:
        return None, None
    key = request.app.state.settings.token_encryption_key
    token = decrypt(row.token_encrypted, key) if key else None
    return token, row.login


@router.get("/github/token")
async def get_token(request: Request, session: AsyncSession = SessionDep) -> dict[str, Any]:
    row_email = _user_email(request)
    if not row_email:
        raise HTTPException(status_code=401, detail="sign in to manage a GitHub token")
    row = (
        await session.execute(sa_select(GithubAccount).where(GithubAccount.email == row_email))
    ).scalars().first()
    if row is None:
        return {"configured": False}
    return {"configured": True, "login": row.login, "created_at": row.created_at.isoformat()}


@router.put("/github/token")
async def put_token(
    request: Request,
    session: AsyncSession = SessionDep,
    token: str = Body(..., embed=True),
) -> dict[str, Any]:
    """Verify the token against GitHub, then store it encrypted."""
    import datetime as dt

    email = _user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="sign in to manage a GitHub token")
    settings = request.app.state.settings
    if not settings.token_encryption_key:
        raise HTTPException(status_code=503, detail="server missing TOKEN_ENCRYPTION_KEY")

    try:
        login = await _await_or_run(GitHubClient(token.strip()).user_login)
    except Exception:
        raise HTTPException(status_code=422, detail="token rejected by GitHub")

    row = (
        await session.execute(sa_select(GithubAccount).where(GithubAccount.email == email))
    ).scalars().first()
    if row is None:
        row = GithubAccount(email=email, token_encrypted="", created_at=dt.datetime.now(dt.timezone.utc))
        session.add(row)
    row.token_encrypted = encrypt(token.strip(), settings.token_encryption_key)
    row.login = login
    await session.commit()
    return {"configured": True, "login": login}


@router.delete("/github/token")
async def delete_token(request: Request, session: AsyncSession = SessionDep) -> dict[str, Any]:
    email = _user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="sign in")
    row = (
        await session.execute(sa_select(GithubAccount).where(GithubAccount.email == email))
    ).scalars().first()
    if row is not None:
        await session.delete(row)
        await session.commit()
    return {"configured": False}


async def _await_or_run(fn):  # tiny helper: run sync client call in a thread
    import asyncio

    return await asyncio.to_thread(fn)


RUNNER_REPO = "26457513/assurance-scan"
STUB_FILENAME = "assurance-scan.yml"
RUNNER_FILENAME = "scan-remote.yml"


@router.post("/scans/remote")
async def scan_remote(
    request: Request,
    session: AsyncSession = SessionDep,
    repo: str = Body(...),
    ref: str = Body(default=""),
) -> dict[str, Any]:
    """Dispatch a scan of any repo the caller's (or org's) token can read.

    Repos with our stub dispatch it directly; everything else runs through
    the scan-remote runner in the assurance-scan repo, which pulls the code
    from this server's tarball proxy.
    """
    import asyncio

    settings = request.app.state.settings
    user_token, _login = await resolve_user_token(request, session)
    token = user_token or settings.github_poll_token
    if not token:
        raise HTTPException(
            status_code=422,
            detail="no GitHub token available — add one in Settings or configure the org token",
        )
    client = GitHubClient(token)
    try:
        resolved_ref = ref.strip() or await asyncio.to_thread(client.repo_default_branch, repo)
        has_stub = await asyncio.to_thread(client.has_workflow, repo, STUB_FILENAME)
        if has_stub:
            await asyncio.to_thread(client.dispatch, repo, STUB_FILENAME, resolved_ref)
            return {"status": "dispatched", "mode": "stub", "repo": repo, "ref": resolved_ref}
        # Remote runner: code arrives via our tarball proxy, never as a token.
        if not settings.runner_pull_token:
            raise HTTPException(status_code=503, detail="server missing RUNNER_PULL_TOKEN")
        await asyncio.to_thread(
            client.dispatch,
            RUNNER_REPO,
            RUNNER_FILENAME,
            "main",
            {"repo": repo, "ref": resolved_ref, "account": _user_email(request) or "org"},
        )
        return {"status": "dispatched", "mode": "runner", "repo": repo, "ref": resolved_ref}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub dispatch failed: {exc}") from exc


@router.get("/internal/tarball")
async def tarball_proxy(
    request: Request,
    session: AsyncSession = SessionDep,
    repo: str = "",
    ref: str = "",
    account: str = "",
    x_runner_token: str = Header(default=""),
) -> Response:
    """Streams a repo tarball to the scan-remote runner.

    Authenticated with RUNNER_PULL_TOKEN (shared between this server and the
    runner workflow); user tokens never leave this server.
    """
    import asyncio

    settings = request.app.state.settings
    if not settings.runner_pull_token or x_runner_token != settings.runner_pull_token:
        raise HTTPException(status_code=401, detail="bad runner token")
    if not repo:
        raise HTTPException(status_code=400, detail="repo required")

    token = None
    if account and account != "org":
        row = (
            await session.execute(sa_select(GithubAccount).where(GithubAccount.email == account))
        ).scalars().first()
        if row is not None and settings.token_encryption_key:
            token = decrypt(row.token_encrypted, settings.token_encryption_key)
    token = token or settings.github_poll_token
    if not token:
        raise HTTPException(status_code=422, detail="no token available for this repo")

    client = GitHubClient(token)
    try:
        data = await asyncio.to_thread(client.tarball, repo, ref or "HEAD")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"tarball fetch failed: {exc}") from exc
    filename = f"{repo.replace('/', '_')}_{urllib.parse.quote(ref or 'HEAD')}.tar.gz"
    return Response(
        content=data,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
