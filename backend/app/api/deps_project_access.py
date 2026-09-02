"""Authenticated project-access dependencies for browser API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_roles import get_current_user
from app.infrastructure.db.models import User
from app.infrastructure.project_access import (
    ADMIN_ROLES,
    ProjectAccessPrincipal,
    SYSTEM_PRINCIPAL,
    sync_github_app_memberships,
    sync_github_memberships,
)
from app.modules.atomic.access.browser_auth import basic_auth_ok


async def get_project_access_principal(
    request: Request,
    session: AsyncSession = SessionDep,
    user: User | None = Depends(get_current_user),
) -> ProjectAccessPrincipal:
    settings = request.app.state.settings
    google_on = bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.session_secret
        and settings.public_base_url
    )
    basic_on = bool(settings.app_auth_user and settings.app_auth_password)
    if basic_on and basic_auth_ok(
        request.headers.get("authorization"),
        settings.app_auth_user,
        settings.app_auth_password,
    ):
        return SYSTEM_PRINCIPAL
    if not google_on and not basic_on:
        return SYSTEM_PRINCIPAL
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="sign in")
    principal = ProjectAccessPrincipal(user_id=user.id, role=user.role)
    if user.role not in ADMIN_ROLES:
        if settings.github_app_access_enabled:
            await sync_github_app_memberships(session, user, settings)
        else:
            await sync_github_memberships(session, user, settings)
    return principal


ProjectAccessDep = Annotated[
    ProjectAccessPrincipal, Depends(get_project_access_principal)
]


__all__ = ["ProjectAccessDep", "get_project_access_principal"]
