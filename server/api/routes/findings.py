"""Findings endpoints: list findings for a scan, or fetch the published findings.json."""
from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.api.schemas.finding import FindingResponse, FindingsListResponse
from server.db.repositories.findings import FindingRepository
from server.db.repositories.runs import RunRepository


router = APIRouter(tags=["findings"])


@router.get("/scans/{run_id}/findings", response_model=FindingsListResponse)
async def list_findings(
    run_id: str,
    severity: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=10000),
    session: AsyncSession = SessionDep,
) -> FindingsListResponse:
    """List normalized findings for a scan, optionally filtered by severity."""
    runs = RunRepository(session)
    findings_repo = FindingRepository(session)

    run = await runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")

    rows = await findings_repo.list_for_run(run_id, severity=severity, limit=limit)
    findings = [_row_to_response(row) for row in rows]
    by_severity = Counter(f.severity for f in findings)
    by_scanner = Counter(f.scanner_kind for f in findings)

    return FindingsListResponse(
        run_id=run_id,
        total=len(findings),
        by_severity=dict(by_severity),
        by_scanner=dict(by_scanner),
        findings=findings,
    )


@router.get("/scans/{run_id}/findings.json", response_class=PlainTextResponse)
async def get_findings_json(run_id: str, session: AsyncSession = SessionDep) -> PlainTextResponse:
    """Return the agent-facing findings.json payload produced at scan end."""
    runs = RunRepository(session)
    run = await runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")
    if not run.findings_json:
        raise HTTPException(status_code=409, detail=f"findings for scan {run_id} not yet published")
    return PlainTextResponse(run.findings_json, media_type="application/json")


def _row_to_response(row) -> FindingResponse:
    return FindingResponse(
        id=row.id,
        run_id=row.run_id,
        scanner_kind=row.scanner_kind,
        rule_id=row.rule_id,
        severity=row.severity,
        file_path=row.file_path,
        line_start=row.line_start,
        line_end=row.line_end,
        message=row.message,
        theme=row.theme,
        fix_strategy=row.fix_strategy,
        compliance_tags=json.loads(row.compliance_tags_json or "[]"),
    )
