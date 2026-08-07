"""Trends endpoint — finding counts and severity breakdowns across runs."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import Finding, Run


router = APIRouter(tags=["trends"])


@router.get("/trends")
async def trends(
    project_path: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Finding-count + severity-broken-down trends over recent runs.

    Returns runs in chronological order (oldest first), so the frontend
    can draw a sparkline. Each entry includes count + severity breakdown.
    """
    run_stmt = select(Run)
    if project_path:
        run_stmt = run_stmt.where(Run.project_path == project_path)
    run_stmt = run_stmt.order_by(Run.started_at.desc()).limit(limit)
    runs = (await session.execute(run_stmt)).scalars().all()
    runs.reverse()  # chronological

    if not runs:
        return {"runs": [], "delta": None}

    # One query: count findings per (run, severity).
    finding_stmt = select(
        Finding.run_id,
        Finding.severity,
        func.count(Finding.id).label("count"),
    ).where(
        Finding.run_id.in_([r.run_id for r in runs])
    ).group_by(Finding.run_id, Finding.severity)

    severity_by_run: dict[str, Counter] = defaultdict(Counter)
    for run_id, sev, count in (await session.execute(finding_stmt)).all():
        severity_by_run[run_id][sev] = count

    entries: list[dict[str, Any]] = []
    for run in runs:
        counts = severity_by_run.get(run.run_id, Counter())
        total = sum(counts.values())
        entries.append({
            "run_id": run.run_id,
            "project_path": run.project_path,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "total_findings": total,
            "by_severity": dict(counts),
        })

    delta = _compute_delta(entries)
    return {"runs": entries, "delta": delta}


def _compute_delta(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Diff the latest entry against the previous one. None if <2 entries."""
    if len(entries) < 2:
        return None
    latest = entries[-1]
    prev = entries[-2]

    severity_delta = {}
    all_severities = set(latest["by_severity"]) | set(prev["by_severity"])
    for sev in all_severities:
        delta = latest["by_severity"].get(sev, 0) - prev["by_severity"].get(sev, 0)
        if delta != 0:
            severity_delta[sev] = delta

    return {
        "vs_run_id": prev["run_id"],
        "total_delta": latest["total_findings"] - prev["total_findings"],
        "by_severity": severity_delta,
    }
