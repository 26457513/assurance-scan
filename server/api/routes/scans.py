"""Scan endpoints: enqueue, list, get-detail."""
from __future__ import annotations

import datetime as dt
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep, QueueDep, get_settings
from server.api.schemas.scan import (
    ScanRequest,
    ScanResponse,
    ScanStatus,
    ScanSummary,
    ScannerStatus,
)
from server.db.repositories.findings import FindingRepository
from server.db.repositories.runs import RunRepository
from server.db.models import Run
from server.db.repositories.scanner_runs import ScannerRunRepository
from server.worker.queue import ScanQueue


log = logging.getLogger(__name__)
router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("", response_model=ScanResponse, status_code=202)
async def start_scan(
    body: ScanRequest,
    session: AsyncSession = SessionDep,
    queue: ScanQueue = QueueDep,
    settings=Depends(get_settings),
) -> ScanResponse:
    """Enqueue a scan. Returns immediately with the run_id."""
    project_path = body.project_path or str(settings.project_root)
    options_json = json.dumps(body.options)

    runs = RunRepository(session)
    run_id = queue.enqueue(project_path=project_path, options=body.options)

    await runs.create(
        run_id=run_id,
        project_path=project_path,
        options_json=options_json,
    )
    await session.commit()

    return ScanResponse(
        run_id=run_id,
        project_path=project_path,
        status="queued",
        queued_at=dt.datetime.now(dt.timezone.utc),
    )


@router.get("", response_model=list[ScanSummary])
async def list_scans(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = SessionDep,
) -> list[ScanSummary]:
    """List recent scans with finding counts."""
    runs = RunRepository(session)
    findings = FindingRepository(session)
    rows = await runs.list_recent(limit=limit)

    summaries: list[ScanSummary] = []
    for run in rows:
        count = await findings.count_for_run(run.run_id)
        summaries.append(
            ScanSummary(
                run_id=run.run_id,
                project_path=run.project_path,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                finding_count=count,
            )
        )
    return summaries


@router.get("/{run_id}", response_model=ScanStatus)
async def get_scan(run_id: str, session: AsyncSession = SessionDep) -> ScanStatus:
    """Get full detail for one scan, including per-scanner status."""
    runs = RunRepository(session)
    scanner_runs = ScannerRunRepository(session)

    run = await runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")

    scanner_rows = await scanner_runs.list_for_run(run_id)
    scanner_status = [
        ScannerStatus(
            kind=r.scanner_kind,
            status=r.status,
            started_at=r.started_at,
            completed_at=r.completed_at,
            error_message=r.error_message,
        )
        for r in scanner_rows
    ]

    return ScanStatus(
        run_id=run.run_id,
        project_path=run.project_path,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        scanner_status=scanner_status,
        options=json.loads(run.options_json or "{}"),
        error_message=run.error_message,
    )


@router.delete("/{run_id}")
async def delete_scan(run_id: str, session: AsyncSession = SessionDep) -> dict:
    """Delete a scan and all its related data (findings, artifacts, test
    results, FR states). Cascade deletes handle the child rows."""
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")
    await session.delete(run)
    await session.commit()
    return {"status": "deleted", "run_id": run_id}


@router.delete("")
async def delete_all_scans(
    project_path: str | None = Query(default=None),
    session: AsyncSession = SessionDep,
) -> dict:
    """Delete all scans, optionally filtered by project_path."""
    from sqlalchemy import select as sa_select
    stmt = sa_select(Run)
    if project_path:
        stmt = stmt.where(Run.project_path == project_path)
    rows = (await session.execute(stmt)).scalars().all()
    count = len(rows)
    for run in rows:
        await session.delete(run)
    await session.commit()
    return {"status": "deleted", "count": count}
