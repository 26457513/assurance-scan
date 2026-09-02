"""Role-based authorization for GitHub-backed server sessions.

Roles: admin (protected, seeded, API-immutable) > superuser (delegated,
revocable) > user (default on first login).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.infrastructure.db.models import User

ADMIN_ROLES = {"admin", "superuser"}
MUTABLE_ROLES = {"user", "superuser"}


async def get_current_user(
    request: Request, session: AsyncSession = SessionDep
) -> User | None:
    """Resolve the user authenticated by the GitHub session middleware."""
    user_id = getattr(request.state, "authenticated_user_id", None)
    if not isinstance(user_id, int) or user_id <= 0:
        return None
    row = await session.get(User, user_id)
    return row if row is not None and row.disabled_at is None else None


def require_role(*roles: str):
    async def dep(user: User | None = Depends(get_current_user)) -> User:
        if user is None or user.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return dep


require_admin = require_role(*ADMIN_ROLES)
