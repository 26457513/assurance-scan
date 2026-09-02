"""GitHub-backed account, role, and MCP credential endpoints."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_roles import MUTABLE_ROLES, get_current_user, require_admin
from app.infrastructure.db.models import User


router = APIRouter(tags=["accounts"])


@router.get("/users/me")
async def who_am_i(user: User | None = Depends(get_current_user)) -> dict[str, Any]:
    if user is None or not user.github_login:
        raise HTTPException(status_code=401, detail="sign in with GitHub")
    return {"id": user.id, "login": user.github_login, "role": user.role}


@router.get("/users")
async def list_users(
    _admin: User = Depends(require_admin),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    rows = (await session.execute(select(User).order_by(User.github_login, User.id))).scalars().all()
    return {
        "users": [
            {
                "id": row.id,
                "login": row.github_login,
                "role": row.role,
                "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
            }
            for row in rows
            if row.github_login
        ]
    }


@router.put("/users")
async def set_user_role(
    _admin: User = Depends(require_admin),
    session: AsyncSession = SessionDep,
    user_id: int = Body(...),
    role: str = Body(...),
) -> dict[str, Any]:
    normalized_role = role.strip().lower()
    if normalized_role not in MUTABLE_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(MUTABLE_ROLES)}")
    row = await session.get(User, user_id)
    if row is None or not row.github_login:
        raise HTTPException(status_code=404, detail="GitHub account not found")
    if row.role == "admin":
        raise HTTPException(status_code=403, detail="admin role is protected")
    row.role = normalized_role
    await session.commit()
    return {"id": row.id, "login": row.github_login, "role": row.role}


def _hash_mcp_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.get("/users/me/mcp-token")
async def get_mcp_token_status(user: User | None = Depends(get_current_user)) -> dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="sign in with GitHub")
    return {
        "has_token": user.mcp_token_hash is not None,
        "generated_at": user.mcp_token_generated_at.isoformat() if user.mcp_token_generated_at else None,
    }


@router.post("/users/me/mcp-token/preview")
async def preview_mcp_token(
    request: Request,
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="sign in with GitHub")
    token = secrets.token_urlsafe(32)
    raw_netloc: object = request.url.netloc
    netloc = raw_netloc.decode() if isinstance(raw_netloc, bytes) else str(raw_netloc)
    base = f"{request.url.scheme}://{netloc}"
    command = (
        "claude mcp remove assurance-scan 2>/dev/null; "
        f"claude mcp add --transport http assurance-scan {base}/mcp "
        f'--header "Authorization: Bearer {token}"'
    )
    return {"token": token, "command": command, "base_url": base}


class ApplyMcpTokenBody(BaseModel):
    token: str


@router.post("/users/me/mcp-token")
async def apply_mcp_token(
    body: ApplyMcpTokenBody,
    user: User | None = Depends(get_current_user),
    session: AsyncSession = SessionDep,
) -> dict[str, str]:
    if user is None:
        raise HTTPException(status_code=401, detail="sign in with GitHub")
    user.mcp_token_hash = _hash_mcp_token(body.token)
    user.mcp_token_generated_at = dt.datetime.now(dt.timezone.utc)
    session.add(user)
    await session.commit()
    return {"status": "activated"}


@router.delete("/users/me/mcp-token")
async def revoke_mcp_token(
    user: User | None = Depends(get_current_user),
    session: AsyncSession = SessionDep,
) -> dict[str, str]:
    if user is None:
        raise HTTPException(status_code=401, detail="sign in with GitHub")
    user.mcp_token_hash = None
    user.mcp_token_generated_at = None
    session.add(user)
    await session.commit()
    return {"status": "revoked"}


__all__ = ["router"]
