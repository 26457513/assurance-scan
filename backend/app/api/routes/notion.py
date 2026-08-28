"""Notion standup digest endpoint."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps_roles import get_current_user
from fastapi import Depends

router = APIRouter(prefix="/notion", tags=["notion"])


@router.post("/digest")
async def post_digest(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Repaint the configured Notion page with the standup digest."""
    from fastapi import HTTPException

    from app.notion_digest import post_digest as _post

    if user is None:
        raise HTTPException(status_code=401, detail="sign in")
    result = await _post(request.app.state.settings)
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result
