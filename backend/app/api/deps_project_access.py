"""Authenticated project-access dependencies for browser API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_roles import get_current_user
from app.infrastructure.db.models import User
from app.infrastructure.project_access import (
    ProjectAccessPrincipal,
    SYSTEM_PRINCIPAL,
    sync_github_app_memberships,
)


async def get_project_access_principal(
    request: Request,
    session: AsyncSession = SessionDep,
    user: User | None = Depends(get_current_user),
) -> ProjectAccessPrincipal:
    if not request.app.state.settings.public_base_url:
        # Explicit local/test mode has no hosted browser identity boundary.
        return SYSTEM_PRINCIPAL
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="sign in with GitHub")
    user_id = user.id
    principal = ProjectAccessPrincipal(user_id=user_id, role=user.role)
    await sync_github_app_memberships(session, user_id, request.app.state.settings)
    return principal


ProjectAccessDep = Annotated[
    ProjectAccessPrincipal, Depends(get_project_access_principal)
]


__all__ = ["ProjectAccessDep", "get_project_access_principal"]
