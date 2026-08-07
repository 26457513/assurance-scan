"""Compliance view (v3 + mapping artifact).

The mapping artifact (`fr-compliance-mapping.json`) connects project FRs
to compliance framework rows. The compliance view:

  /api/compliance                        → list frameworks the mapping covers
  /api/compliance/{framework}            → matrix of rows with derived state

Each row's state is the worst state across its `satisfied_by` FRs in
the latest run for the project. Rationale + confidence from the mapping
are surfaced so the user can review agent proposals.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import ComplianceMapping, FrState, Run


router = APIRouter(tags=["compliance"])


# Severity ladder (worst first). Used to derive a row's "worst" state
# from the set of FR states that satisfy it.
_SEVERITY_ORDER: tuple[str, ...] = (
    "failed",
    "pending",
    "untested",
    "blocked",
    "waived",
    "passed",
)


@router.get("/compliance")
async def list_frameworks(
    project_path: str | None = Query(default=None),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """List compliance frameworks that appear in any project's mapping."""
    stmt = select(ComplianceMapping)
    if project_path:
        stmt = stmt.where(ComplianceMapping.project_path == project_path)
    rows = (await session.execute(stmt.order_by(
        ComplianceMapping.loaded_at.desc()
    ))).scalars().all()

    framework_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "frs": 0})
    for mapping_row in rows:
        doc = json.loads(mapping_row.mapping_doc_json)
        for entry in doc.get("mappings", []):
            ruleset = entry.get("ruleset", "")
            if not ruleset:
                continue
            framework_counts[ruleset]["rows"] += 1
            framework_counts[ruleset]["frs"] += len(entry.get("satisfied_by", []))

    return {
        "frameworks": [
            {"id": fw, "rows": c["rows"], "frs": c["frs"]}
            for fw, c in sorted(framework_counts.items())
        ]
    }


@router.get("/compliance/{framework}")
async def compliance_matrix(
    framework: str,
    project_path: str | None = Query(default=None),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Return compliance-row → state matrix for one framework.

    For each row in the mapping:
      - satisfied_by: list of FR IDs from the mapping
      - state: worst state across those FRs in the latest run
      - rationale: from the mapping (agent's reasoning)
      - confidence: agent's self-assessment
    """
    mapping_stmt = select(ComplianceMapping)
    if project_path:
        mapping_stmt = mapping_stmt.where(ComplianceMapping.project_path == project_path)
    mapping_stmt = mapping_stmt.order_by(ComplianceMapping.loaded_at.desc()).limit(1)
    mapping_row = (await session.execute(mapping_stmt)).scalars().first()

    if mapping_row is None:
        raise HTTPException(
            status_code=404,
            detail="no compliance mapping loaded — run a scan with fr-compliance-mapping.json present",
        )

    mapping_doc = json.loads(mapping_row.mapping_doc_json)
    entries = [
        m for m in mapping_doc.get("mappings", [])
        if m.get("ruleset") == framework
    ]
    if not entries:
        raise HTTPException(
            status_code=404,
            detail=f"no mapping entries for framework '{framework}'",
        )

    # Latest run for the project (for state lookups).
    run_stmt = select(Run).where(Run.project_path == mapping_row.project_path)
    run_stmt = run_stmt.order_by(Run.started_at.desc()).limit(1)
    run = (await session.execute(run_stmt)).scalars().first()

    # Build FR-state index for the latest run.
    state_by_fr: dict[str, str] = {}
    if run:
        state_rows = (await session.execute(
            select(FrState).where(FrState.run_id == run.run_id)
        )).scalars().all()
        state_by_fr = {s.fr_id: s.state for s in state_rows}

    matrix: list[dict[str, Any]] = []
    for entry in entries:
        fr_ids = entry.get("satisfied_by", [])
        fr_states = [state_by_fr.get(fid, "untested") for fid in fr_ids]
        worst = _worst_state(fr_states)
        matrix.append({
            "row_id": entry["row"],
            "version": entry.get("version"),
            "fr_ids": fr_ids,
            "fr_states": dict(zip(fr_ids, fr_states)),
            "worst_state": worst,
            "rationale": entry.get("rationale", ""),
            "confidence": entry.get("confidence", "medium"),
        })

    matrix.sort(key=lambda e: e["row_id"])

    summary: dict[str, int] = defaultdict(int)
    for entry in matrix:
        summary[entry["worst_state"]] += 1

    return {
        "framework": framework,
        "project_path": mapping_row.project_path,
        "mapping_loaded_at": mapping_row.loaded_at.isoformat(),
        "mapping_hash": mapping_row.content_hash,
        "run_id": run.run_id if run else None,
        "row_count": len(matrix),
        "summary": dict(summary),
        "rows": matrix,
    }


def _worst_state(states: list[str]) -> str:
    """Pick the most-attention state across a list."""
    if not states:
        return "untested"
    for sev in _SEVERITY_ORDER:
        if sev in states:
            return sev
    return "untested"
