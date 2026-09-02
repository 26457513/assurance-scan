"""Temporary, feature-gated GitHub account-linking OAuth flow."""

from __future__ import annotations

import asyncio
import datetime as dt
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_roles import get_current_user
from app.infrastructure.db.models import GithubAccount, User
from app.infrastructure.db.repositories.github_account_links import (
    SqlAlchemyGithubAccountLinkRepository,
)
from app.infrastructure.db.repositories.identity_sessions import (
    SecureIdentityRandom,
    SqlAlchemyBrowserSessionRepository,
    SqlAlchemyGithubOauthStateRepository,
)
from app.infrastructure.github_oauth import exchange_and_verify_github_authorization
from app.modules.atomic.access.github_account_link import (
    GithubAccountLinkError,
    LinkGithubAccountCommand,
    link_github_account,
)
from app.modules.atomic.access.github_oauth_state import (
    GithubOauthFlow,
    issue_github_oauth_state,
)
from app.modules.atomic.access.server_session import (
    authenticate_browser_session,
    issue_browser_session,
)


router = APIRouter(prefix="/v2/github/link", tags=["github-link"])
_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_LINK_COOKIE = "as_github_link"
_KEY_ID = "primary"


def _require_enabled(request: Request) -> None:
    settings = request.app.state.settings
    if not getattr(settings, "migration_github_linking_enabled", False):
        raise HTTPException(status_code=404, detail="not found")
    if not all(
        (
            settings.github_app_client_id,
            settings.github_app_client_secret,
            settings.token_encryption_key,
            settings.public_base_url,
        )
    ):
        raise HTTPException(status_code=503, detail="GitHub linking is not configured")


@router.get("/status")
async def github_account_link_status(
    request: Request,
    user: User | None = Depends(get_current_user),
    session: AsyncSession = SessionDep,
) -> dict[str, object]:
    """Expose only whether the temporary migration action should be shown."""
    settings = request.app.state.settings
    enabled = bool(
        getattr(settings, "migration_github_linking_enabled", False)
        and settings.github_app_client_id
        and settings.github_app_client_secret
        and settings.token_encryption_key
        and settings.public_base_url
    )
    if user is None:
        return {"enabled": False, "linked": False, "login": None}
    account = (
        await session.execute(select(GithubAccount).where(GithubAccount.user_id == user.id))
    ).scalar_one_or_none()
    return {
        "enabled": enabled,
        "linked": account is not None and account.disconnected_at is None,
        "login": account.login_at_last_verify if account is not None else None,
    }


@router.get("/start")
async def start_github_account_link(
    request: Request,
    user: User | None = Depends(get_current_user),
    session: AsyncSession = SessionDep,
) -> RedirectResponse:
    _require_enabled(request)
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="existing sign-in is required")
    settings = request.app.state.settings
    now = dt.datetime.now(dt.timezone.utc)
    random = SecureIdentityRandom()
    issued_session = issue_browser_session(user_id=user.id, now=now, random=random)
    await SqlAlchemyBrowserSessionRepository(session).create(issued_session.record)
    material = issue_github_oauth_state(
        browser_session_id=issued_session.record.session_id,
        flow_kind=GithubOauthFlow.LINK,
        return_path="/setup",
        now=now,
        random=random,
    )
    await SqlAlchemyGithubOauthStateRepository(
        session,
        encryption_keys={_KEY_ID: settings.token_encryption_key},
        active_key_id=_KEY_ID,
    ).create(material)
    callback = f"{settings.public_base_url}/api/v2/github/link/callback"
    query = urllib.parse.urlencode(
        {
            "client_id": settings.github_app_client_id,
            "redirect_uri": callback,
            "state": material.state,
            "code_challenge": material.pkce_challenge,
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(f"{_AUTHORIZE_URL}?{query}", status_code=302)
    response.set_cookie(
        _LINK_COOKIE,
        issued_session.cookie_value,
        max_age=600,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
        path="/api/v2/github/link/callback",
    )
    return response


@router.get("/callback")
async def finish_github_account_link(
    request: Request,
    code: str = "",
    state: str = "",
    user: User | None = Depends(get_current_user),
    session: AsyncSession = SessionDep,
) -> RedirectResponse:
    _require_enabled(request)
    if user is None or user.disabled_at is not None or not code or not state:
        raise HTTPException(status_code=401, detail="existing sign-in and OAuth proof are required")
    user_id = user.id
    settings = request.app.state.settings
    now = dt.datetime.now(dt.timezone.utc)
    cookie = request.cookies.get(_LINK_COOKIE, "")
    sessions = SqlAlchemyBrowserSessionRepository(session)
    session_record = await sessions.find_by_cookie(cookie)
    authenticated = authenticate_browser_session(cookie, session_record, now=now)
    if not authenticated.authenticated or authenticated.user_id != user_id or session_record is None:
        raise HTTPException(status_code=401, detail="GitHub linking transaction is invalid")
    consumed = await SqlAlchemyGithubOauthStateRepository(
        session,
        encryption_keys={_KEY_ID: settings.token_encryption_key},
        active_key_id=_KEY_ID,
    ).consume(state, browser_session_id=session_record.session_id, now=now)
    if consumed is None or consumed.flow_kind is not GithubOauthFlow.LINK:
        raise HTTPException(status_code=401, detail="GitHub linking transaction is invalid")
    try:
        authorization = await asyncio.to_thread(
            exchange_and_verify_github_authorization,
            code=code,
            verifier=consumed.pkce_verifier,
            client_id=settings.github_app_client_id,
            client_secret=settings.github_app_client_secret,
        )
        await link_github_account(
            LinkGithubAccountCommand(
                user_id=user_id,
                github_user_id=authorization.github_user_id,
                login=authorization.login,
                user_token=authorization.access_token,
                refresh_token=authorization.refresh_token,
                token_expires_at=now + dt.timedelta(seconds=authorization.expires_in_seconds),
                verified_at=now,
            ),
            linked_at=now,
            repository=SqlAlchemyGithubAccountLinkRepository(
                session, encryption_key=settings.token_encryption_key, key_id=_KEY_ID
            ),
        )
    except GithubAccountLinkError as exc:
        raise HTTPException(status_code=409, detail="GitHub identity link requires operator resolution") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="GitHub authorization could not be verified") from exc
    await sessions.revoke(session_record.session_id, now=now)
    response = RedirectResponse(f"{consumed.return_path}?github_link=linked", status_code=302)
    response.delete_cookie(_LINK_COOKIE, path="/api/v2/github/link/callback")
    return response
