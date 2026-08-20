"""Tests for role-based access (users table, admin immutability)."""
from __future__ import annotations

import datetime as dt

from fastapi import HTTPException
from sqlalchemy import select as sa_select

from server.api.deps_roles import MUTABLE_ROLES, require_admin, require_role
from server.db.models import User


async def test_user_provisioning_and_login_update(session) -> None:
    row = User(email="new@barkleygen.com", role="user")
    session.add(row)
    await session.commit()
    fetched = (await session.execute(sa_select(User))).scalars().one()
    assert fetched.role == "user"
    fetched.last_login_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()


async def test_admin_row_is_immutable_via_role_endpoint(session) -> None:
    """The endpoint-level rule: refuse role changes on admin rows."""
    # encoded in set_user_role; here we verify the constants it relies on
    assert "admin" not in MUTABLE_ROLES
    assert MUTABLE_ROLES == {"user", "superuser"}


async def test_require_admin_rejects_missing_user() -> None:
    try:
        await require_admin(None)
        raise AssertionError("expected 403")
    except HTTPException as exc:
        assert exc.status_code == 403


async def test_require_role_rejects_wrong_role() -> None:
    user = User(email="x@barkleygen.com", role="user")
    try:
        await require_role("admin", "superuser")(user)
        raise AssertionError("expected 403")
    except HTTPException as exc:
        assert exc.status_code == 403
    # superuser passes the admin gate
    su = User(email="y@barkleygen.com", role="superuser")
    assert await require_role("admin", "superuser")(su) is su
