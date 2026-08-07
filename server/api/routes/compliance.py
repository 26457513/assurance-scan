"""Compliance view per framework.

Aggregates FR states by their `satisfies` compliance tags. Returns a
matrix of compliance-row → state for a given framework (or all), using
the latest run for the project.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import Fr, FrState, Run


router = APIRouter(tags=["compliance"])


# Parse "ASVS:v5.0.0-5.1.1" -> ("ASVS", "v5.0.0-5.1.1")
_FRAMEWORK_RE = re.compile(r"^([A-Za-z0-9-]+):(.+)$")


def _split_tag(tag: str) -> tuple[str, str] | None:
    m = _FRAMEWORK_RE.match(tag)
    if not m:
        return None
    return m.group(1), m.group(2)


@router.get("/compliance")
async def list_frameworks(
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """List the frameworks that appear in any project's FRs, with counts."""
    rows = (await session.execute(
        select(Fr.project_path, Fr.satisfies_json, Fr.fr_id)
    )).all()

    framework_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "frs": 0})
    for project_path, satisfies_json, _fr_id in rows:
        satisfies = json.loads(satisfies_json or "[]")
        seen = set()
        for tag in satisfies:
            split = _split_tag(tag)
            if split is None:
                continue
            fw, row = split
            if row not in seen:
                framework_counts[fw]["rows"] += 1
                seen.add(row)
            framework_counts[fw]["frs"] += 1

    return {
        "frameworks": [
            {"id": fw, "rows": counts["rows"], "frs": counts["frs"]}
            for fw, counts in sorted(framework_counts.items())
        ]
    }


@router.get("/compliance/{framework}")
async def compliance_matrix(
    framework: str,
    project_path: str | None = Query(default=None, description="Filter to one project."),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Return compliance-row → state matrix for one framework.

    Each row: { row_id, fr_ids, state, projects }.
    State is the worst (most-attention-needed) across FRs that satisfy it.
    """
    # Collect all FRs that satisfy at least one row in this framework.
    fr_rows = (await session.execute(
        select(Fr).order_by(Fr.id.desc())
    )).scalars().all()

    # Index by (project, fr_id) -> satisfies rows in this framework
    fr_index: dict[tuple[str, str], list[str]] = {}
    for fr in fr_rows:
        if project_path and fr.project_path != project_path:
            continue
        satisfies = json.loads(fr.satisfies_json or "[]")
        rows_for_fw = []
        for tag in satisfies:
            split = _split_tag(tag)
            if split is None:
                continue
            fw, row = split
            if fw == framework:
                rows_for_fw.append(row)
        if rows_for_fw:
            fr_index[(fr.project_path, fr.fr_id)] = rows_for_fw

    if not fr_index:
        raise HTTPException(
            status_code=404,
            detail=f"no FRs satisfy framework '{framework}'"
            + (f" in project '{project_path}'" if project_path else ""),
        )

    # Look up latest run per project.
    latest_runs: dict[str, str] = {}
    for (proj, _fr) in fr_index:
        if proj in latest_runs:
            continue
        run_row = (await session.execute(
            select(Run)
            .where(Run.project_path == proj)
            .order_by(Run.started_at.desc())
            .limit(1)
        )).scalars().first()
        if run_row:
            latest_runs[proj] = run_row.run_id

    # Get latest state for each FR.
    state_rows = (await session.execute(
        select(FrState).where(
            FrState.run_id.in_(list(latest_runs.values()))
        )
    )).scalars().all()
    state_by_proj_fr: dict[tuple[str, str], str] = {}
    for s in state_rows:
        state_by_proj_fr[(s.project_path, s.fr_id)] = s.state

    # Build matrix.
    matrix: dict[str, dict[str, Any]] = {}
    for (proj, fr_id), rows in fr_index.items():
        state = state_by_proj_fr.get((proj, fr_id), "untested")
        for row_id in rows:
            entry = matrix.setdefault(row_id, {
                "row_id": row_id,
                "fr_ids": [],
                "states": [],
                "projects": [],
                "worst_state": "untested",
            })
            entry["fr_ids"].append(fr_id)
            entry["states"].append(state)
            entry["projects"].append(proj)

    # Compute worst state per row.
    for row_id, entry in matrix.items():
        entry["worst_state"] = _worst_state(entry["states"])

    # Sort by row_id (best-effort natural sort)
    sorted_rows = sorted(matrix.values(), key=lambda e: e["row_id"])

    summary = {
        fw: 0 for fw in ["passed", "failed", "manual-review", "blocked", "waived",
                          "has-evidence", "to-be-tested", "untested"]
    }
    for entry in sorted_rows:
        summary[entry["worst_state"]] += 1

    return {
        "framework": framework,
        "row_count": len(sorted_rows),
        "summary": summary,
        "rows": sorted_rows,
    }


# Severity ladder (worst first). Used to pick the most-attention state
# across multiple FRs that satisfy one compliance row.
_SEVERITY_ORDER: tuple[str, ...] = (
    "failed",
    "manual-review",
    "blocked",
    "to-be-tested",
    "untested",
    "has-evidence",
    "waived",
    "passed",
)


def _worst_state(states: list[str]) -> str:
    """Return the most-attention state across the input list."""
    if not states:
        return "untested"
    for sev in _SEVERITY_ORDER:
        if sev in states:
            return sev
    return "untested"
