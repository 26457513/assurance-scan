"""SSE endpoint for live scan progress.

GET /api/scans/{run_id}/stream
  Returns text/event-stream. Each event has an id (monotonic), event
  name (scan_started | scanner_started | scanner_completed | scan_completed),
  and a JSON data payload.

  Last-Event-ID header is honored for resume: events with id > header
  value are replayed from the in-memory buffer (capacity 1000/run).
  Older events fall back to a snapshot GET /api/scans/{run_id}.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.infrastructure.db.repositories.runs import RunRepository
from app.events import bus


router = APIRouter(tags=["stream"])


@router.get("/scans/{run_id}/stream")
async def stream_scan(
    run_id: str,
    request: Request,
    session: AsyncSession = SessionDep,
) -> StreamingResponse:
    """Stream live scan events as SSE."""
    runs = RunRepository(session)
    run = await runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")

    # Last-Event-ID header from the client, if reconnecting.
    last_event_id = _parse_last_event_id(request.headers.get("last-event-id"))

    return StreamingResponse(
        _event_stream(run_id, last_event_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx: don't buffer SSE
        },
    )


async def _event_stream(
    run_id: str,
    after_id: int,
    request: Request,
) -> AsyncIterator[bytes]:
    """Yield SSE-formatted events until the client disconnects or scan ends."""
    queue = await bus.subscribe(run_id, after_id=after_id)
    try:
        while True:
            if await request.is_disconnected():
                return
            try:
                eid, kind, payload = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                # Heartbeat keeps the connection alive through proxies.
                yield b": heartbeat\n\n"
                continue

            data = json.dumps(payload, sort_keys=True)
            chunk = f"id: {eid}\nevent: {kind}\ndata: {data}\n\n"
            yield chunk.encode()

            if kind == "scan_completed":
                return
    finally:
        bus.unsubscribe(run_id, queue)


def _parse_last_event_id(header_value: str | None) -> int:
    if not header_value:
        return 0
    try:
        return int(header_value)
    except ValueError:
        return 0
