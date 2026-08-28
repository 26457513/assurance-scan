"""Health endpoint — no auth, for container healthcheck."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.deps import SettingsDep
from app.config import Settings


router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str               # "ok" | "degraded" | "down"
    db: str                   # "ok" | "down"
    docker_socket: str        # "ok" | "down"
    version: str
    uptime_seconds: int


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, settings: Settings = SettingsDep) -> HealthResponse:
    started_at = getattr(request.app.state, "started_at", None)
    uptime = 0
    if started_at:
        uptime = int((asyncio.get_event_loop().time() - started_at))

    db_status = await _check_db()
    docker_status = _check_docker_socket(settings)

    overall = "ok" if (db_status == "ok" and docker_status == "ok") else "degraded"
    if db_status == "down":
        overall = "down"

    return HealthResponse(
        status=overall,
        db=db_status,
        docker_socket=docker_status,
        version="2.0.0-dev",
        uptime_seconds=uptime,
    )


async def _check_db() -> str:
    try:
        from app.infrastructure.db.connection import get_engine
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return "ok"
    except Exception:
        return "down"


def _check_docker_socket(settings: Settings) -> str:
    return "ok" if Path(settings.docker_socket).exists() else "down"
