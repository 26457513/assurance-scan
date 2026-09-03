"""Thin HTTP adapter for the version-two Setup projection."""

from __future__ import annotations

import datetime as dt
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_roles import get_current_user
from app.infrastructure.db.models import User
from app.infrastructure.db.repositories.setup_projection import (
    SetupCursorError,
    SqlAlchemySetupProjectionRepository,
)
from app.infrastructure.project_access import sync_github_app_memberships
from app.modules.atomic.access.setup_state import repository_page_payload, setup_payload
from app.modules.workflows.setup_bootstrap import SetupLinks, setup_bootstrap, setup_repositories


router = APIRouter(prefix="/v2/setup", tags=["setup-v2"])
_DECIMAL_ID = re.compile(r"^[1-9][0-9]{0,18}$")
_MAX_DATABASE_ID = 9_223_372_036_854_775_807
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get("")
async def get_setup_bootstrap(
    request: Request,
    github_repository_id: str | None = Query(default=None),
    installations_cursor: str | None = Query(default=None, max_length=512),
    user: User | None = Depends(get_current_user),
    session: AsyncSession = SessionDep,
) -> JSONResponse:
    """Return one discriminated Setup snapshot for an explicit selection."""
    _require_enabled(request)
    if user is not None and user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="account is disabled")
    user_id = None
    if user is not None:
        user_id = user.id
        await sync_github_app_memberships(session, user_id, request.app.state.settings)
    repository_id = _optional_github_id(github_repository_id)
    sign_in_url = "/auth/login?next=/setup"
    try:
        result = await setup_bootstrap(
            user_id=user_id,
            selected_repository_id=repository_id,
            installations_cursor=installations_cursor,
            now=dt.datetime.now(dt.timezone.utc),
            repository=SqlAlchemySetupProjectionRepository(session),
            links=SetupLinks(
                sign_in_url=sign_in_url,
                install_url="/api/v2/github/install/start",
            ),
        )
    except SetupCursorError as exc:
        raise HTTPException(status_code=422, detail="invalid Setup cursor") from exc
    return JSONResponse(setup_payload(result), headers=_NO_STORE)


@router.get("/repositories")
async def get_setup_repositories(
    request: Request,
    github_installation_id: str = Query(),
    query: str = Query(default="", max_length=128),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=25, ge=1),
    user: User | None = Depends(get_current_user),
    session: AsyncSession = SessionDep,
) -> JSONResponse:
    """Search repositories proven by the caller's current entitlement rows."""
    _require_enabled(request)
    if user is None:
        raise HTTPException(status_code=401, detail="sign in is required")
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="account is disabled")
    user_id = user.id
    if not await sync_github_app_memberships(session, user_id, request.app.state.settings):
        raise HTTPException(status_code=503, detail="GitHub access could not be refreshed")
    installation_id = _github_id(github_installation_id)
    try:
        result = await setup_repositories(
            user_id=user_id,
            github_installation_id=installation_id,
            query=query,
            cursor=cursor,
            limit=min(limit, 50),
            now=dt.datetime.now(dt.timezone.utc),
            repository=SqlAlchemySetupProjectionRepository(session),
        )
    except SetupCursorError as exc:
        raise HTTPException(status_code=422, detail="invalid Setup cursor") from exc
    return JSONResponse(repository_page_payload(result), headers=_NO_STORE)


def _require_enabled(request: Request) -> None:
    if not getattr(request.app.state.settings, "github_app_access_enabled", False):
        raise HTTPException(status_code=404, detail="not found")


def _optional_github_id(value: str | None) -> int | None:
    return _github_id(value) if value is not None else None


def _github_id(value: str) -> int:
    if not _DECIMAL_ID.fullmatch(value):
        raise HTTPException(status_code=422, detail="invalid GitHub identifier")
    parsed = int(value)
    if parsed > _MAX_DATABASE_ID:
        raise HTTPException(status_code=422, detail="invalid GitHub identifier")
    return parsed


__all__ = ["router"]
