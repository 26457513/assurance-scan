"""Permanent GitHub-only browser authentication routes."""

from __future__ import annotations

import asyncio
import datetime as dt
import urllib.parse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.config import account_identity_is_ready
from app.infrastructure.db.repositories.github_signin import SqlAlchemyGithubSigninRepository
from app.infrastructure.db.repositories.identity_sessions import (
    SecureIdentityRandom,
    SqlAlchemyBrowserSessionRepository,
)
from app.infrastructure.github_oauth import exchange_and_verify_github_authorization
from app.modules.atomic.access.github_signin_transaction import issue_github_signin
from app.modules.atomic.access.server_session import SESSION_COOKIE_NAME, issue_browser_session


router = APIRouter(tags=["github-auth"])
_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TRANSACTION_COOKIE = "as_github_signin"
_CALLBACK_PATH = "/auth/github/callback"


def _require_ready(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.github_app_access_enabled or not account_identity_is_ready(settings):
        raise HTTPException(status_code=503, detail="GitHub sign-in is not configured")


@router.get("/auth/github/start")
async def start_github_signin(
    request: Request,
    session: AsyncSession = SessionDep,
    next_path: str = Query(default="/", alias="next"),
) -> RedirectResponse:
    _require_ready(request)
    settings = request.app.state.settings
    now = dt.datetime.now(dt.timezone.utc)
    try:
        material = issue_github_signin(
            return_path=next_path,
            now=now,
            random=SecureIdentityRandom(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="GitHub sign-in return path is invalid") from exc
    await SqlAlchemyGithubSigninRepository(
        session, encryption_key=settings.token_encryption_key
    ).create(material)
    callback = f"{settings.public_base_url}{_CALLBACK_PATH}"
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
        _TRANSACTION_COOKIE,
        material.transaction_cookie,
        max_age=600,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
        path=_CALLBACK_PATH,
    )
    return response


@router.get(_CALLBACK_PATH)
async def finish_github_signin(
    request: Request,
    session: AsyncSession = SessionDep,
    code: str = "",
    state: str = "",
    error: str = "",
) -> Response:
    _require_ready(request)
    if error:
        return JSONResponse({"detail": "GitHub authorization was declined"}, status_code=401)
    if not code or not state:
        raise HTTPException(status_code=400, detail="GitHub authorization proof is missing")
    settings = request.app.state.settings
    now = dt.datetime.now(dt.timezone.utc)
    repository = SqlAlchemyGithubSigninRepository(
        session, encryption_key=settings.token_encryption_key
    )
    consumed = await repository.consume(
        state=state,
        transaction_cookie=request.cookies.get(_TRANSACTION_COOKIE, ""),
        now=now,
    )
    if consumed is None:
        raise HTTPException(status_code=401, detail="GitHub sign-in transaction is invalid or expired")
    try:
        authorization = await asyncio.to_thread(
            exchange_and_verify_github_authorization,
            code=code,
            verifier=consumed.pkce_verifier,
            client_id=settings.github_app_client_id,
            client_secret=settings.github_app_client_secret,
        )
        user = await repository.resolve_user(
            authorization,
            now=now,
            admin_github_ids=settings.github_admin_user_ids,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="account is disabled") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="GitHub authorization could not be verified") from exc
    issued = issue_browser_session(user_id=user.id, now=now, random=SecureIdentityRandom())
    await SqlAlchemyBrowserSessionRepository(session).create(issued.record)
    response = RedirectResponse(consumed.return_path, status_code=302)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        issued.cookie_value,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
        path="/",
    )
    response.delete_cookie(_TRANSACTION_COOKIE, path=_CALLBACK_PATH)
    return response


@router.get("/auth/logout")
async def github_logout(request: Request, session: AsyncSession = SessionDep) -> RedirectResponse:
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    repository = SqlAlchemyBrowserSessionRepository(session)
    record = await repository.find_by_cookie(cookie)
    if record is not None:
        await repository.revoke(record.session_id, now=dt.datetime.now(dt.timezone.utc))
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


__all__ = ["router"]
