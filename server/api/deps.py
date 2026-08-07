"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from server.config import Settings
from server.db.connection import get_session
from server.worker.queue import ScanQueue


async def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_scan_queue(request: Request) -> ScanQueue:
    return request.app.state.scan_queue


SettingsDep = Depends(get_settings)
SessionDep = Depends(get_session)
QueueDep = Depends(get_scan_queue)
