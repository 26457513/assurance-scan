"""Findings endpoints: list findings for a scan, or fetch the published findings.json."""
from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.schemas.finding import FindingResponse, FindingsListResponse
from app.infrastructure.db.models import FindingAcceptance
from app.infrastructure.db.repositories.findings import FindingRepository
from app.infrastructure.db.repositories.runs import RunRepository
from sqlalchemy import select
from pydantic import BaseModel
import datetime as _dt


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


# ---------------------------------------------------------------------------
# Per-finding risk acceptance (triage board)
# ---------------------------------------------------------------------------

class AcceptFindingRequest(BaseModel):
    project_path: str
    scanner_kind: str
    rule_id: str
    risk_level: str
    rationale: str
    fix_assessment: str | None = None
    invalidation_conditions: str | None = None
    accepted_by: str = "user"


@router.post("/findings/accept")
async def accept_finding(
    req: AcceptFindingRequest,
    session: AsyncSession = SessionDep,
) -> dict:
    """Accept a finding as non-exploitable. Persists across scans — the
    matcher will filter this (scanner_kind, rule_id) from future evaluations."""
    existing = (await session.execute(
        select(FindingAcceptance).where(
            FindingAcceptance.project_path == req.project_path,
            FindingAcceptance.scanner_kind == req.scanner_kind,
            FindingAcceptance.rule_id == req.rule_id,
        )
    )).scalars().first()
    if existing:
        existing.risk_level = req.risk_level
        existing.rationale = req.rationale
        existing.fix_assessment = req.fix_assessment
        existing.invalidation_conditions = req.invalidation_conditions
        existing.accepted_by = req.accepted_by
        existing.accepted_at = _dt.datetime.now(_dt.timezone.utc)
    else:
        session.add(FindingAcceptance(
            project_path=req.project_path,
            scanner_kind=req.scanner_kind,
            rule_id=req.rule_id,
            risk_level=req.risk_level,
            rationale=req.rationale,
            fix_assessment=req.fix_assessment,
            invalidation_conditions=req.invalidation_conditions,
            accepted_by=req.accepted_by,
            accepted_at=_dt.datetime.now(_dt.timezone.utc),
        ))
    await session.commit()
    return {"status": "accepted"}


@router.delete("/findings/accept/{acceptance_id}")
async def unaccept_finding(
    acceptance_id: int,
    session: AsyncSession = SessionDep,
) -> dict:
    """Undo a finding acceptance. The finding becomes actionable again."""
    row = await session.get(FindingAcceptance, acceptance_id)
    if row is None:
        raise HTTPException(status_code=404, detail="acceptance not found")
    await session.delete(row)
    await session.commit()
    return {"status": "removed"}


@router.get("/findings/accepted")
async def list_accepted(
    project_path: str = Query(...),
    session: AsyncSession = SessionDep,
) -> dict:
    """List active finding acceptances for a project."""
    rows = (await session.execute(
        select(FindingAcceptance)
        .where(FindingAcceptance.project_path == project_path)
        .order_by(FindingAcceptance.accepted_at.desc())
    )).scalars().all()
    now = _dt.datetime.now(_dt.timezone.utc)
    return {
        "acceptances": [
            {
                "id": r.id,
                "scanner_kind": r.scanner_kind,
                "rule_id": r.rule_id,
                "risk_level": r.risk_level,
                "rationale": r.rationale,
                "fix_assessment": r.fix_assessment,
                "invalidation_conditions": r.invalidation_conditions,
                "accepted_by": r.accepted_by,
                "accepted_at": r.accepted_at.isoformat(),
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "active": r.expires_at is None or r.expires_at > now,
            }
            for r in rows
        ]
    }
