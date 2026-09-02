"""Trends endpoint — finding counts and severity breakdowns across runs."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_project_access import ProjectAccessDep
from app.infrastructure.db.models import Finding, Run
from app.infrastructure.project_access import (
    require_project,
    shared_github_run_clause,
    visible_project_ids,
)


router = APIRouter(tags=["trends"])


@router.get("/trends")
async def trends(
    principal: ProjectAccessDep,
    project_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Finding-count + severity-broken-down trends over recent runs.

    Returns runs in chronological order (oldest first), so the frontend
    can draw a sparkline. Each entry includes count + severity breakdown.
    """
    # Shared trends intentionally exclude private local work and retained
    # server-era runs. Local scans are available only as an owner-private
    # overlay, never as shared project history.
    run_stmt = select(Run).where(
        shared_github_run_clause(),
        Run.legacy_retained.is_(False),
    )
    if project_id is not None:
        project = await require_project(session, principal, project_id)
        if project is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="project not found")
        run_stmt = run_stmt.where(Run.project_id == project_id)
    else:
        allowed_ids = await visible_project_ids(session, principal)
        if allowed_ids is not None:
            run_stmt = run_stmt.where(Run.project_id.in_(allowed_ids))
    run_stmt = run_stmt.order_by(Run.started_at.desc()).limit(limit)
    runs = list((await session.execute(run_stmt)).scalars().all())
    runs.reverse()  # chronological

    if not runs:
        return {"runs": [], "delta": None}

    # One query: count findings per (run, severity).
    finding_stmt = (
        select(
            Finding.run_id,
            Finding.severity,
            func.count(Finding.id).label("count"),
        )
        .where(Finding.run_id.in_([r.run_id for r in runs]))
        .group_by(Finding.run_id, Finding.severity)
    )

    tribal_stmt = (
        select(
            Finding.run_id,
            func.count(Finding.id).label("count"),
        )
        .where(
            Finding.run_id.in_([r.run_id for r in runs]),
            Finding.scanner_kind == "tribal",
        )
        .group_by(Finding.run_id)
    )

    severity_by_run: dict[str, Counter] = defaultdict(Counter)
    for run_id, sev, count in (await session.execute(finding_stmt)).all():
        severity_by_run[run_id][sev] = count
    tribal_by_run = {run_id: count for run_id, count in (await session.execute(tribal_stmt)).all()}

    entries: list[dict[str, Any]] = []
    for run in runs:
        counts = severity_by_run.get(run.run_id, Counter())
        total = sum(counts.values())
        entries.append(
            {
                "run_id": run.run_id,
                "project_id": run.project_id,
                "origin": run.origin,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "total_findings": total,
                "by_severity": dict(counts),
                "git_branch": run.git_branch,
                "commit_sha": run.commit_sha,
                "working_tree_dirty": run.working_tree_dirty,
                "repository": run.repository_full_name_at_scan,
                "tribal": tribal_by_run.get(run.run_id, 0),
            }
        )

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
