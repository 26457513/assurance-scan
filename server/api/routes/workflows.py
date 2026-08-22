"""Workflow catalogue for the UI — the same source of truth the MCP
`list_workflows` tool serves, over REST."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("")
async def list_workflows_route() -> dict[str, Any]:
    from server.workflows import list_workflows

    return {"workflows": list_workflows()}
