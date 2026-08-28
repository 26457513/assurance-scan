"""Role-based authorization: current-user lookup + role dependencies.

Roles: admin (protected, seeded, API-immutable) > superuser (delegated,
revocable) > user (default on first login).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.infrastructure.db.models import User
from app.modules.atomic.access.browser_auth import verify_session

ADMIN_ROLES = {"admin", "superuser"}
MUTABLE_ROLES = {"user", "superuser"}


async def get_current_user(
    request: Request, session: AsyncSession = SessionDep
) -> User | None:
    """Resolve the signed-in user, provisioning on first login."""
    import datetime as dt

    from sqlalchemy import select as sa_select

    settings = request.app.state.settings
    if not settings.session_secret:
        return None
    email = verify_session(request.cookies.get("as_session"), settings.session_secret)
    if not email:
        return None
    row = (
        await session.execute(sa_select(User).where(User.email == email))
    ).scalars().first()
    if row is None:
        row = User(email=email, role="user")
        session.add(row)
    row.last_login_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()
    return row


def require_role(*roles: str):
    async def dep(user: User | None = Depends(get_current_user)) -> User:
        if user is None or user.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return dep


require_admin = require_role(*ADMIN_ROLES)
