"""FR list endpoint — flat matrix of all FRs for the latest catalogue.

Returns each FR with: state, required-evidence summary, collected-
evidence count, gap flag. Drives the /frs UI page.

Distinct from /api/frs/{fr_id} (single-FR detail with history) and
/api/compliance/{framework} (FRs grouped by compliance tag).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import CatalogueSnapshot, Evidence, Fr, FrState, Run


router = APIRouter(tags=["frs"])


@router.get("/frs")
async def list_frs(
    project_path: str | None = Query(default=None),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Flat list of FRs for the most recent catalogue snapshot.

    Each entry: id, title, state, required_evidence counts (all_of / any_of
    / none_of), evidence count, is_gap.
    """
    # Find the latest catalogue snapshot for the project.
    snapshot_stmt = select(CatalogueSnapshot)
    if project_path:
        snapshot_stmt = snapshot_stmt.where(CatalogueSnapshot.project_path == project_path)
    snapshot_stmt = snapshot_stmt.order_by(CatalogueSnapshot.created_at.desc()).limit(1)
    snapshot = (await session.execute(snapshot_stmt)).scalars().first()

    if snapshot is None:
        return {"frs": [], "catalogue": None, "run_id": None}

    # Latest run for the project (for state and evidence lookups).
    run_stmt = (
        select(Run)
        .where(Run.project_path == snapshot.project_path)
        .order_by(Run.started_at.desc())
        .limit(1)
    )
    run = (await session.execute(run_stmt)).scalars().first()

    fr_rows = (await session.execute(
        select(Fr).where(Fr.catalogue_snapshot_id == snapshot.id).order_by(Fr.fr_id)
    )).scalars().all()

    # Eager-load state and evidence counts.
    state_by_fr: dict[str, str] = {}
    evidence_count_by_fr: dict[str, int] = {}
    if run:
        state_rows = (await session.execute(
            select(FrState).where(FrState.run_id == run.run_id)
        )).scalars().all()
        state_by_fr = {s.fr_id: s.state for s in state_rows}

        ev_count_rows = (await session.execute(
            select(Evidence.fr_id, func.count(Evidence.id))
            .where(Evidence.run_id == run.run_id)
            .group_by(Evidence.fr_id)
        )).all()
        evidence_count_by_fr = {fr_id: count for fr_id, count in ev_count_rows}

    GAP_STATES = {"untested", "to-be-tested", "failed", "manual-review", "blocked"}

    entries = []
    for fr in fr_rows:
        required = json.loads(fr.required_evidence_json or "{}")
        all_of = len(required.get("all_of") or [])
        any_of = len(required.get("any_of") or [])
        none_of = len(required.get("none_of") or [])
        state = state_by_fr.get(fr.fr_id, "untested")
        entries.append({
            "fr_id": fr.fr_id,
            "title": fr.title,
            "state": state,
            "is_gap": state in GAP_STATES,
            "required_evidence_counts": {
                "all_of": all_of,
                "any_of": any_of,
                "none_of": none_of,
                "total": all_of + any_of + none_of,
            },
            "evidence_count": evidence_count_by_fr.get(fr.fr_id, 0),
            "satisfies": json.loads(fr.satisfies_json or "[]"),
            "depends_on": json.loads(fr.depends_on_json or "[]"),
        })

    summary = {
        "total": len(entries),
        "passed": sum(1 for e in entries if e["state"] == "passed"),
        "failed": sum(1 for e in entries if e["state"] == "failed"),
        "gaps": sum(1 for e in entries if e["is_gap"]),
        "waived": sum(1 for e in entries if e["state"] == "waived"),
    }

    return {
        "catalogue": {
            "project": snapshot.project_path,
            "catalogue_version": snapshot.catalogue_version,
            "fr_count": len(fr_rows),
            "snapshot_id": snapshot.id,
            "created_at": snapshot.created_at.isoformat(),
        },
        "run_id": run.run_id if run else None,
        "summary": summary,
        "frs": entries,
    }
