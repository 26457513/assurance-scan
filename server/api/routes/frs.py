"""FR detail endpoint.

Returns everything the FR detail page needs in one call: the FR's
required_evidence, collected evidence for the latest run, current state,
and state history across runs.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import CatalogueSnapshot, Fr, FrState, Run
from server.db.repositories.evidence import EvidenceRepository


router = APIRouter(tags=["frs"])


@router.get("/frs/{fr_id}")
async def get_fr_detail(
    fr_id: str,
    run_id: str | None = Query(default=None, description="Specific run; defaults to latest for the project."),
    session: AsyncSession = SessionDep,
) -> dict:
    """Full per-FR detail: required evidence, collected evidence, current state."""
    # Find the FR row in any catalogue snapshot (latest wins).
    stmt = select(Fr).where(Fr.fr_id == fr_id).order_by(Fr.id.desc()).limit(1)
    result = await session.execute(stmt)
    fr = result.scalars().first()
    if fr is None:
        raise HTTPException(status_code=404, detail=f"FR {fr_id} not found")

    # Determine the run to use.
    if run_id is None:
        run_stmt = (
            select(Run)
            .where(Run.project_path == fr.project_path)
            .order_by(Run.started_at.desc())
            .limit(1)
        )
        run_row = (await session.execute(run_stmt)).scalars().first()
        if run_row is None:
            raise HTTPException(status_code=404, detail="no runs for this project")
        run_id = run_row.run_id

    # Collected evidence for this FR in this run.
    evidence_repo = EvidenceRepository(session)
    evidence_rows = await evidence_repo.list_for_fr(fr.project_path, fr_id, run_id)

    # Current computed state.
    state_stmt = (
        select(FrState)
        .where(FrState.fr_id == fr_id, FrState.run_id == run_id)
        .order_by(FrState.computed_at.desc())
        .limit(1)
    )
    state_row = (await session.execute(state_stmt)).scalars().first()

    return {
        "fr_id": fr.fr_id,
        "title": fr.title,
        "description": fr.description,
        "implemented_by": json.loads(fr.implemented_by_json or "[]"),
        "required_evidence": json.loads(fr.required_evidence_json or "{}"),
        "satisfies": json.loads(fr.satisfies_json or "[]"),
        "depends_on": json.loads(fr.depends_on_json or "[]"),
        "project_path": fr.project_path,
        "run_id": run_id,
        "state": state_row.state if state_row else "untested",
        "reason": json.loads(state_row.reason_json) if state_row else {},
        "evidence": [
            {
                "id": e.id,
                "type": e.type,
                "source": json.loads(e.source_json or "{}"),
                "result": e.result,
                "collected_at": e.collected_at.isoformat() if e.collected_at else None,
                "notes": e.notes,
            }
            for e in evidence_rows
        ],
    }


@router.get("/frs/{fr_id}/history")
async def get_fr_history(
    fr_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = SessionDep,
) -> dict:
    """State transitions for an FR across recent runs."""
    stmt = (
        select(FrState, Run)
        .join(Run, FrState.run_id == Run.run_id)
        .where(FrState.fr_id == fr_id)
        .order_by(FrState.computed_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()

    return {
        "fr_id": fr_id,
        "history": [
            {
                "run_id": state.run_id,
                "state": state.state,
                "reason": json.loads(state.reason_json or "{}"),
                "computed_at": state.computed_at.isoformat() if state.computed_at else None,
                "run_started_at": run.started_at.isoformat() if run.started_at else None,
            }
            for state, run in rows
        ],
    }
