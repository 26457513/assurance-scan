"""Findings endpoints: list findings for a scan, or fetch the published findings.json."""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_project_access import ProjectAccessDep
from app.api.schemas.finding import (
    FindingResponse,
    FindingsListResponse,
    SourceContextResponse,
)
from app.infrastructure.db.models import Finding, FindingAcceptance
from app.infrastructure.db.repositories.findings import FindingRepository
from app.infrastructure.db.repositories.source_contexts import SourceContextRepository
from app.infrastructure.project_access import require_project, require_run


router = APIRouter(tags=["findings"])


@router.get("/scans/{run_id}/findings", response_model=FindingsListResponse)
async def list_findings(
    run_id: str,
    principal: ProjectAccessDep,
    severity: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=10000),
    session: AsyncSession = SessionDep,
) -> FindingsListResponse:
    """List normalized findings for a scan, optionally filtered by severity."""
    findings_repo = FindingRepository(session)

    run = await require_run(session, principal, run_id)
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
async def get_findings_json(
    run_id: str,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
) -> PlainTextResponse:
    """Return the agent-facing findings.json payload produced at scan end."""
    run = await require_run(session, principal, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")
    if not run.findings_json:
        raise HTTPException(status_code=409, detail=f"findings for scan {run_id} not yet published")
    return PlainTextResponse(run.findings_json, media_type="application/json")


@router.get(
    "/scans/{run_id}/findings/{finding_id}/source-context",
    response_model=SourceContextResponse,
)
async def get_source_context(
    run_id: str,
    finding_id: int,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
) -> SourceContextResponse:
    """Return only source captured from the immutable scanned snapshot."""

    if await require_run(session, principal, run_id) is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")
    finding = await session.get(Finding, finding_id)
    if finding is None or finding.run_id != run_id:
        raise HTTPException(status_code=404, detail="finding not found")
    context = await SourceContextRepository(session).get_for_finding(run_id, finding_id)
    if context is None:
        return SourceContextResponse(available=False, unavailable_reason="not_uploaded")
    return SourceContextResponse(
        available=context.available,
        provider=context.provider,
        path=context.file_path,
        window_start=context.window_start,
        window_end=context.window_end,
        highlight_start=context.highlight_start,
        highlight_end=context.highlight_end,
        highlight_truncated=context.highlight_truncated,
        lines=json.loads(context.lines_json),
        source_hash=context.source_hash,
        redaction_version=context.redaction_version,
        redaction_changed=context.redaction_changed,
        unavailable_reason=context.unavailable_reason,
    )


def _row_to_response(row) -> FindingResponse:
    return FindingResponse(
        id=row.id,
        finding_key=row.finding_key,
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
        package_name=row.package_name,
        package_version=row.package_version,
        package_ecosystem=row.package_ecosystem,
        package_purl=row.package_purl,
    )


# ---------------------------------------------------------------------------
# Per-finding risk acceptance (triage board)
# ---------------------------------------------------------------------------

class AcceptFindingRequest(BaseModel):
    project_id: int
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
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
) -> dict:
    """Accept a finding as non-exploitable. Persists across scans — the
    matcher will filter this (scanner_kind, rule_id) from future evaluations."""
    if await require_project(session, principal, req.project_id, "manage") is None:
        raise HTTPException(status_code=404, detail="project not found")
    existing = (await session.execute(
        select(FindingAcceptance).where(
            FindingAcceptance.project_id == req.project_id,
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
        existing.accepted_at = dt.datetime.now(dt.timezone.utc)
    else:
        session.add(FindingAcceptance(
            project_id=req.project_id,
            scanner_kind=req.scanner_kind,
            rule_id=req.rule_id,
            risk_level=req.risk_level,
            rationale=req.rationale,
            fix_assessment=req.fix_assessment,
            invalidation_conditions=req.invalidation_conditions,
            accepted_by=req.accepted_by,
            accepted_at=dt.datetime.now(dt.timezone.utc),
        ))
    await session.commit()
    return {"status": "accepted"}


@router.delete("/findings/accept/{acceptance_id}")
async def unaccept_finding(
    acceptance_id: int,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
) -> dict:
    """Undo a finding acceptance. The finding becomes actionable again."""
    row = await session.get(FindingAcceptance, acceptance_id)
    if row is None:
        raise HTTPException(status_code=404, detail="acceptance not found")
    if await require_project(session, principal, row.project_id, "manage") is None:
        raise HTTPException(status_code=404, detail="acceptance not found")
    await session.delete(row)
    await session.commit()
    return {"status": "removed"}


@router.get("/findings/accepted")
async def list_accepted(
    principal: ProjectAccessDep,
    project_id: int = Query(...),
    session: AsyncSession = SessionDep,
) -> dict:
    """List active finding acceptances for a project."""
    if await require_project(session, principal, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    rows = (await session.execute(
        select(FindingAcceptance)
        .where(FindingAcceptance.project_id == project_id)
        .order_by(FindingAcceptance.accepted_at.desc())
    )).scalars().all()
    now = dt.datetime.now(dt.timezone.utc)
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
