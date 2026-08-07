"""FR detail endpoint (v3)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import Fr, FrState, Run, TestResult


router = APIRouter(tags=["frs"])


@router.get("/frs/{fr_id}")
async def get_fr_detail(
    fr_id: str,
    run_id: str | None = Query(default=None),
    session: AsyncSession = SessionDep,
) -> dict:
    """Full per-FR detail: tests, evaluated results, state."""
    # Get the FR row from any snapshot (latest wins).
    stmt = select(Fr).where(Fr.fr_id == fr_id).order_by(Fr.id.desc()).limit(1)
    result = await session.execute(stmt)
    fr = result.scalars().first()
    if fr is None:
        raise HTTPException(status_code=404, detail=f"FR {fr_id} not found")

    # Load tests from the catalogue snapshot JSON.
    from server.db.models import CatalogueSnapshot
    snapshot = await session.get(CatalogueSnapshot, fr.catalogue_snapshot_id)
    snapshot_doc = json.loads(snapshot.snapshot_json) if snapshot else {}
    tests_for_fr = []
    for fr_doc in snapshot_doc.get("frs", []):
        if fr_doc.get("id") == fr_id:
            tests_for_fr = fr_doc.get("tests") or []
            break

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

    # Test results for this FR.
    tr_rows = (await session.execute(
        select(TestResult).where(
            TestResult.fr_id == fr_id, TestResult.run_id == run_id
        ).order_by(TestResult.test_id)
    )).scalars().all()
    results_by_test = {tr.test_id: tr for tr in tr_rows}

    # State.
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
        "category": fr.category or "",
        "implemented_by": json.loads(fr.implemented_by_json or "[]"),
        "tests": [
            {
                **test,
                "result": results_by_test[test["id"]].result if test.get("id") in results_by_test else "pending",
                "detail": json.loads(results_by_test[test["id"]].detail_json) if test.get("id") in results_by_test else {},
            }
            for test in tests_for_fr
        ],
        "satisfies": json.loads(fr.satisfies_json or "[]"),
        "depends_on": json.loads(fr.depends_on_json or "[]"),
        "project_path": fr.project_path,
        "run_id": run_id,
        "state": state_row.state if state_row else "untested",
        "reason": json.loads(state_row.reason_json) if state_row else {},
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
