"""Per-user GitHub tokens + remote scan dispatch + runner tarball proxy."""
from __future__ import annotations


from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

import datetime as dt
import urllib.error
from typing import Any, Optional

from fastapi import Depends

from server.api.deps import SessionDep
from server.api.deps_roles import get_current_user, require_admin
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


async def resolve_repo_token(
    request: Request, session: AsyncSession, repo: str
) -> tuple[str | None, str | None]:
    """Token for acting on a repo: the user's, else its registered org's,
    else the home-org token. Returns (token, source) for error messaging."""
    settings = request.app.state.settings
    user_token, login = await resolve_user_token(request, session)
    if user_token:
        return user_token, f"user:{login}"
    owner = repo.split("/")[0] if "/" in repo else ""
    if owner and owner != settings.github_org and settings.token_encryption_key:
        from sqlalchemy import select as _select

        from server.db.models import Organisation
        from server.secrets import decrypt as _decrypt

        row = (
            await session.execute(_select(Organisation).where(Organisation.name == owner))
        ).scalars().first()
        if row is not None:
            tok = _decrypt(row.token_encrypted, settings.token_encryption_key)
            if tok:
                return tok, f"org:{owner}"
    return (settings.github_poll_token or None), f"home:{settings.github_org}"


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


async def _await_or_run(fn, *args):  # run a sync client call in a thread
    import asyncio

    return await asyncio.to_thread(fn, *args)


@router.get("/users/me")
async def who_am_i(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="sign in")
    return {"email": user.email, "role": user.role}


@router.get("/users")
async def list_users(
    user: Any = Depends(require_admin),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    from sqlalchemy import select as _select

    from server.db.models import User

    rows = (await session.execute(_select(User).order_by(User.email))).scalars().all()
    return {"users": [
        {"email": r.email, "role": r.role, "last_login_at": r.last_login_at.isoformat() if r.last_login_at else None}
        for r in rows
    ]}


@router.put("/users")
async def set_user_role(
    user: Any = Depends(require_admin),
    session: AsyncSession = SessionDep,
    email: str = Body(...),
    role: str = Body(...),
) -> dict[str, Any]:
    """Set a user's role. Admin rows are immutable; only user/superuser
    are assignable."""
    from sqlalchemy import select as _select

    from server.api.deps_roles import MUTABLE_ROLES
    from server.db.models import User

    role = role.strip().lower()
    if role not in MUTABLE_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(MUTABLE_ROLES)}")
    row = (await session.execute(_select(User).where(User.email == email.strip()))).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="user not found (they must log in once first)")
    if row.role == "admin":
        raise HTTPException(status_code=403, detail="admin role is protected")
    row.role = role
    await session.commit()
    return {"email": row.email, "role": row.role}


@router.get("/orgs")
async def list_orgs(request: Request, session: AsyncSession = SessionDep) -> dict[str, Any]:
    if not _user_email(request):
        raise HTTPException(status_code=401, detail="sign in")
    from server.db.models import Organisation

    rows = (await session.execute(sa_select(Organisation).order_by(Organisation.name))).scalars().all()
    orgs = []
    home = request.app.state.settings.github_org
    if home:
        orgs.append({"name": home, "login": None, "created_at": None, "home": True})
    orgs.extend({"name": r.name, "login": r.login, "created_at": r.created_at.isoformat()} for r in rows)
    return {"orgs": orgs}


@router.put("/orgs")
async def put_org(
    request: Request,
    user: Any = Depends(require_admin),
    session: AsyncSession = SessionDep,
    name: str = Body(...),
    token: str = Body(...),
) -> dict[str, Any]:
    """Register a GitHub organisation: verify the token, store it encrypted."""
    import datetime as dt
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
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"token cannot read organisation '{name}': {exc}. "
                "Check the token's Resource owner is the organisation itself "
                "and that the org allows fine-grained PATs "
                "(org Settings > Personal access tokens)."
            ),
        )

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
async def delete_org(
    request: Request,
    user: Any = Depends(require_admin),
    session: AsyncSession = SessionDep,
    name: str = Query(...),
) -> dict[str, Any]:
    from server.db.models import Organisation

    if name == request.app.state.settings.github_org:
        raise HTTPException(status_code=403, detail="the home organisation is configured via the server .env and cannot be removed here")
    row = (await session.execute(sa_select(Organisation).where(Organisation.name == name))).scalars().first()
    if row is not None:
        await session.delete(row)
        await session.commit()
    return {"status": "removed", "name": name}


STUB_FILENAME = "assurance-scan.yml"


async def _org_registered(request: Request, session: AsyncSession, repo: str) -> bool:
    """True if the repo's org is the home org or a registered organisation."""
    from sqlalchemy import select as _select

    from server.db.models import Organisation

    settings = request.app.state.settings
    owner = repo.split("/")[0] if "/" in repo else ""
    if owner and owner == settings.github_org:
        return True
    row = (
        await session.execute(
            _select(Organisation).where(Organisation.name == owner)
        )
    ).scalars().first()
    return row is not None


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
    token, source = await resolve_repo_token(request, session, repo)
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
        # GitHub dispatches the workflow as it exists ON the target ref —
        # branches that predate the stub 422 with a confusing message.
        default_branch = await asyncio.to_thread(client.repo_default_branch, repo)
        if resolved_ref != default_branch:
            try:
                await asyncio.to_thread(
                    client.file_contents, repo, resolved_ref,
                    f".github/workflows/{STUB_FILENAME}",
                )
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"branch '{resolved_ref}' does not include the assurance-scan "
                            f"workflow — merge {default_branch} into it (or add the stub) "
                            "and scan again."
                        ),
                    ) from exc
                raise
        await asyncio.to_thread(client.dispatch, repo, STUB_FILENAME, resolved_ref)
        return {
            "status": "dispatched",
            "mode": "stub",
            "repo": repo,
            "ref": resolved_ref,
            **({"warning": "organisation not registered — results will not appear in the dashboard; register it in Settings"}
              if not await _org_registered(request, session, repo) else {}),
        }
    except HTTPException:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{repo} is not visible to the resolved credential ({source}) "
                    "or has no assurance-scan workflow. Add the stub "
                    "(templates/assurance-scan.yml) or register the organisation "
                    "in Settings."
                ),
            ) from exc
        if exc.code == 422:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"branch '{resolved_ref}' has an assurance-scan workflow without the "
                    f"workflow_dispatch trigger — merge {default_branch} into it and retry."
                ),
            ) from exc
        raise HTTPException(status_code=502, detail=f"GitHub dispatch failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub dispatch failed: {exc}") from exc



def _hash_mcp_token(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


@router.get("/users/me/mcp-token")
async def get_mcp_token_status(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="sign in")
    return {
        "has_token": user.mcp_token_hash is not None,
        "generated_at": user.mcp_token_generated_at.isoformat() if user.mcp_token_generated_at else None,
    }


@router.post("/users/me/mcp-token/preview")
async def preview_mcp_token(
    request: Request,
    user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    """Generate a candidate token + command without activating it.

    The candidate is inert until applied via POST /users/me/mcp-token.
    """
    import secrets as _secrets

    if user is None:
        raise HTTPException(status_code=401, detail="sign in")
    token = _secrets.token_urlsafe(32)
    netloc = request.url.netloc
    if isinstance(netloc, bytes):  # httpx URLs in tests; starlette gives str
        netloc = netloc.decode()
    base = f"{request.url.scheme}://{netloc}"
    # Drop any stale registration first (non-fatal when absent), then add.
    command = (
        f'claude mcp remove assurance-scan 2>/dev/null; '
        f'claude mcp add --transport http assurance-scan {base}/mcp '
        f'--header "Authorization: Bearer {token}"'
    )
    return {"token": token, "command": command, "base_url": base}


class ApplyMcpTokenBody(BaseModel):
    token: str


@router.post("/users/me/mcp-token")
async def apply_mcp_token(
    user: Any = Depends(get_current_user),
    session: AsyncSession = SessionDep,
    body: ApplyMcpTokenBody = Body(...),
) -> dict[str, Any]:
    """Activate a previewed token. Any previous token stops working."""
    if user is None:
        raise HTTPException(status_code=401, detail="sign in")
    user.mcp_token_hash = _hash_mcp_token(body.token)
    user.mcp_token_generated_at = dt.datetime.now(dt.timezone.utc)
    session.add(user)
    await session.commit()
    return {"status": "activated"}


@router.delete("/users/me/mcp-token")
async def revoke_mcp_token(
    user: Any = Depends(get_current_user),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="sign in")
    user.mcp_token_hash = None
    user.mcp_token_generated_at = None
    session.add(user)
    await session.commit()
    return {"status": "revoked"}
