"""Feature-gated GitHub App installation and setup-return workflow."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_roles import get_current_user
from app.infrastructure.db.models import GithubAccount, User
from app.infrastructure.db.repositories.github_installation_states import (
    SqlAlchemyGithubInstallationStateRepository,
)
from app.infrastructure.db.repositories.github_reconciliation import (
    SqlAlchemyGithubRepositoryReconciliationRepository,
)
from app.infrastructure.db.repositories.identity_sessions import (
    SecureIdentityRandom,
    SqlAlchemyBrowserSessionRepository,
)
from app.infrastructure.github_app_api import (
    GithubAppApiError,
    fetch_authoritative_installation_for_user,
    load_github_app_private_key,
)
from app.modules.atomic.access.github_installation_state import (
    issue_github_installation_state,
)
from app.modules.atomic.access.github_repository_reconciliation import (
    ReconciliationValidationError,
    reconcile_github_repositories,
)
from app.modules.atomic.access.server_session import (
    authenticate_browser_session,
    issue_browser_session,
)
from app.secrets import decrypt


router = APIRouter(prefix="/v2/github", tags=["github-app-setup"])
_INSTALL_URL = "https://github.com/apps/{slug}/installations/new"
_COOKIE = "as_github_install"
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")


def _settings(request: Request):
    settings = request.app.state.settings
    if not getattr(settings, "github_app_access_enabled", False):
        raise HTTPException(status_code=404, detail="not found")
    if (
        not all(
            (
                settings.github_app_id,
                settings.github_app_slug,
                settings.github_app_private_key_path,
                settings.token_encryption_key,
                settings.public_base_url,
            )
        )
        or _SLUG.fullmatch(settings.github_app_slug) is None
    ):
        raise HTTPException(status_code=503, detail="GitHub App access is not configured")
    return settings


async def _linked_account(session: AsyncSession, user_id: int) -> GithubAccount:
    account = (
        await session.execute(
            select(GithubAccount).where(
                GithubAccount.user_id == user_id,
                GithubAccount.github_user_id.isnot(None),
                GithubAccount.disconnected_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if account is None or account.encrypted_user_token is None:
        raise HTTPException(status_code=409, detail="GitHub authorization is required")
    return account


@router.get("/install/start")
async def start_github_app_installation(
    request: Request,
    user: User | None = Depends(get_current_user),
    session: AsyncSession = SessionDep,
) -> RedirectResponse:
    """Begin an installation transaction without accepting repository input."""
    settings = _settings(request)
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="GitHub-linked sign-in is required")
    await _linked_account(session, user.id)
    now = dt.datetime.now(dt.timezone.utc)
    random = SecureIdentityRandom()
    browser = issue_browser_session(user_id=user.id, now=now, random=random)
    await SqlAlchemyBrowserSessionRepository(session).create(browser.record)
    state = issue_github_installation_state(
        browser_session_id=browser.record.session_id,
        return_path="/setup",
        now=now,
        random=random,
    )
    await SqlAlchemyGithubInstallationStateRepository(session).create(state)
    location = _INSTALL_URL.format(slug=settings.github_app_slug)
    response = RedirectResponse(f"{location}?{urllib.parse.urlencode({'state': state.state})}", status_code=302)
    response.set_cookie(
        _COOKIE,
        browser.cookie_value,
        max_age=600,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
        path="/api/v2/github/setup-return",
    )
    return response


@router.get("/setup-return")
async def finish_github_app_installation(
    request: Request,
    state: str = "",
    setup_action: str = "",
    installation_id: int | None = None,
    user: User | None = Depends(get_current_user),
    session: AsyncSession = SessionDep,
) -> RedirectResponse:
    """Consume setup state, prove user access and reconcile authoritative scope."""
    settings = _settings(request)
    if user is None or user.disabled_at is not None or not state:
        raise HTTPException(status_code=401, detail="installation transaction is invalid")
    user_id = user.id
    now = dt.datetime.now(dt.timezone.utc)
    sessions = SqlAlchemyBrowserSessionRepository(session)
    session_record = await sessions.find_by_cookie(request.cookies.get(_COOKIE, ""))
    authenticated = authenticate_browser_session(request.cookies.get(_COOKIE, ""), session_record, now=now)
    if not authenticated.authenticated or authenticated.user_id != user_id or session_record is None:
        raise HTTPException(status_code=401, detail="installation transaction is invalid")
    consumed = await SqlAlchemyGithubInstallationStateRepository(session).consume(
        state,
        browser_session_id=session_record.session_id,
        now=now,
    )
    if consumed is None:
        raise HTTPException(status_code=401, detail="installation transaction is invalid")
    try:
        if setup_action == "request":
            return _redirect(
                f"{consumed.return_path}?github_install=approval_requested",
            )
        if setup_action not in {"install", "update"} or installation_id is None or installation_id <= 0:
            raise HTTPException(status_code=400, detail="GitHub returned an invalid installation result")
        account = await _linked_account(session, user_id)
        token_expires_at = _aware(account.token_expires_at)
        if token_expires_at is not None and token_expires_at <= now:
            raise HTTPException(status_code=409, detail="GitHub authorization must be renewed")
        user_token = decrypt(account.encrypted_user_token or "", settings.token_encryption_key)
        if not user_token:
            raise HTTPException(status_code=503, detail="GitHub authorization is unavailable")
        try:
            private_key = load_github_app_private_key(settings.github_app_private_key_path)
            snapshot = await asyncio.to_thread(
                fetch_authoritative_installation_for_user,
                user_token=user_token,
                github_app_id=settings.github_app_id,
                private_key_pem=private_key,
                github_installation_id=installation_id,
                now=now,
            )
            await reconcile_github_repositories(
                snapshot,
                verified_at=now,
                repository=SqlAlchemyGithubRepositoryReconciliationRepository(session),
            )
        except GithubAppApiError as exc:
            raise HTTPException(status_code=502, detail="GitHub installation could not be verified") from exc
        except ReconciliationValidationError as exc:
            raise HTTPException(
                status_code=409,
                detail="GitHub installation identity requires operator review",
            ) from exc
        return _redirect(
            f"{consumed.return_path}?github_install=ready",
        )
    finally:
        await sessions.revoke(session_record.session_id, now=now)


def _redirect(location: str) -> RedirectResponse:
    response = RedirectResponse(location, status_code=302)
    response.delete_cookie(_COOKIE, path="/api/v2/github/setup-return")
    return response


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.timezone.utc)
