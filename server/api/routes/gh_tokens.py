"""Per-user GitHub tokens + remote scan dispatch + runner tarball proxy."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
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


@router.get("/orgs")
async def list_orgs(request: Request, session: AsyncSession = SessionDep) -> dict[str, Any]:
    if not _user_email(request):
        raise HTTPException(status_code=401, detail="sign in")
    from server.db.models import Organisation

    rows = (await session.execute(sa_select(Organisation).order_by(Organisation.name))).scalars().all()
    return {"orgs": [{"name": r.name, "login": r.login, "created_at": r.created_at.isoformat()} for r in rows]}


@router.put("/orgs")
async def put_org(
    request: Request,
    session: AsyncSession = SessionDep,
    name: str = Body(...),
    token: str = Body(...),
) -> dict[str, Any]:
    """Register a GitHub organisation: verify the token, store it encrypted."""
    import datetime as dt

    if not _user_email(request):
        raise HTTPException(status_code=401, detail="sign in")
    settings = request.app.state.settings
    if not settings.token_encryption_key:
        raise HTTPException(status_code=503, detail="server missing TOKEN_ENCRYPTION_KEY")

    name = name.strip()
    client = GitHubClient(token.strip())
    try:
        login = await _await_or_run(client.user_login)
    except Exception:
        raise HTTPException(status_code=422, detail="token rejected by GitHub")
    # The token must actually see the org's repos.
    try:
        repos = await _await_or_run(client.org_repos, name)
    except Exception:
        raise HTTPException(status_code=422, detail=f"token cannot read organisation '{name}'")

    from server.db.models import Organisation

    row = (await session.execute(sa_select(Organisation).where(Organisation.name == name))).scalars().first()
    if row is None:
        row = Organisation(name=name, token_encrypted="", created_at=dt.datetime.now(dt.timezone.utc))
        session.add(row)
    row.token_encrypted = encrypt(token.strip(), settings.token_encryption_key)
    row.login = login
    await session.commit()
    return {"status": "registered", "name": name, "login": login, "repos_visible": len(repos)}


@router.delete("/orgs")
async def delete_org(request: Request, session: AsyncSession = SessionDep, name: str = Query(...)) -> dict[str, Any]:
    if not _user_email(request):
        raise HTTPException(status_code=401, detail="sign in")
    from server.db.models import Organisation

    row = (await session.execute(sa_select(Organisation).where(Organisation.name == name))).scalars().first()
    if row is not None:
        await session.delete(row)
        await session.commit()
    return {"status": "removed", "name": name}


STUB_FILENAME = "assurance-scan.yml"


@router.post("/scans/remote")
async def scan_remote(
    request: Request,
    session: AsyncSession = SessionDep,
    repo: str = Body(...),
    ref: str = Body(default=""),
) -> dict[str, Any]:
    """Dispatch a scan of a repo that carries the assurance-scan stub.

    The run executes in the target repo on its own compute. Repos without
    the stub are refused with setup guidance — this instance never runs
    scans on behalf of repos that haven't adopted the workflow.
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
        if not has_stub:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{repo} has no assurance-scan workflow. Add the stub "
                    "(templates/assurance-scan.yml) to the repo's "
                    ".github/workflows/ to enable scanning."
                ),
            )
        await asyncio.to_thread(client.dispatch, repo, STUB_FILENAME, resolved_ref)
        return {"status": "dispatched", "mode": "stub", "repo": repo, "ref": resolved_ref}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub dispatch failed: {exc}") from exc

