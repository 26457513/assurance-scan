"""FR detail endpoint (v3)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import CatalogueSnapshot, ComplianceMapping, Fr, FrState, Run, TestResult, Waiver


router = APIRouter(tags=["frs"])


async def _derive_satisfies(session: AsyncSession, project_path: str, fr_id: str) -> list[dict]:
    """Derive compliance-row references for an FR from the mapping table.

    The mapping file owns ASVS↔FR relationships now; the catalogue no longer
    carries `satisfies`. This reverse-lookup reads the latest ComplianceMapping
    and collects all appropriate rows that reference this FR.
    """
    mapping_stmt = (
        select(ComplianceMapping)
        .where(ComplianceMapping.project_path == project_path)
        .order_by(ComplianceMapping.loaded_at.desc())
        .limit(1)
    )
    mapping_row = (await session.execute(mapping_stmt)).scalars().first()
    if mapping_row is None:
        return []
    mapping_doc = json.loads(mapping_row.mapping_doc_json)
    result = []
    for entry in mapping_doc.get("mappings", []):
        if not entry.get("appropriate", True):
            continue
        if fr_id in entry.get("satisfied_by", []):
            result.append({
                "ruleset": entry.get("ruleset", ""),
                "row": entry.get("row", ""),
            })
    return result


@router.post("/catalogue")
async def save_catalogue(
    project_path: str = Query(...),
    catalogue_json: str = Body(..., embed=True),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Validate and store an FR catalogue snapshot for a project.

    REST mirror of the MCP save_catalogue tool: same validation, same
    snapshot storage. Used by the FRs page's paste flow.
    """
    from server.catalogue.loader import load_catalogue_from_dict
    from server.db.repositories.catalogue_snapshots import CatalogueSnapshotRepository
    from server.db.repositories.frs import FrRepository

    try:
        doc = json.loads(catalogue_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc

    try:
        catalogue = load_catalogue_from_dict(doc, project_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"catalogue validation failed: {exc}") from exc

    snap_repo = CatalogueSnapshotRepository(session)
    fr_repo = FrRepository(session)
    snapshot = await snap_repo.store(
        project_path=project_path,
        catalogue=catalogue.doc,
        catalogue_version=catalogue.doc.get("catalogue_version"),
    )
    await fr_repo.bulk_insert_for_snapshot(
        snapshot.id, project_path, catalogue.doc.get("frs", [])
    )
    await session.commit()
    return {
        "status": "saved",
        "project": catalogue.doc.get("project"),
        "catalogue_version": catalogue.doc.get("catalogue_version"),
        "fr_count": len(catalogue.doc.get("frs", [])),
        "content_hash": catalogue.content_hash,
    }


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

    # Active waiver (if state is waived) — surface the human-readable reason.
    import datetime as _dt
    waiver_row = None
    if state_row and state_row.state == "waived":
        now = _dt.datetime.now(_dt.timezone.utc)
        waiver_rows = (await session.execute(
            select(Waiver)
            .where(Waiver.project_path == fr.project_path, Waiver.fr_id == fr_id)
            .order_by(Waiver.waived_at.desc())
        )).scalars().all()
        for w in waiver_rows:
            if w.expires_at is None or w.expires_at > now:
                waiver_row = w
                break

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
        "satisfies": await _derive_satisfies(session, fr.project_path, fr.fr_id),
        "depends_on": json.loads(fr.depends_on_json or "[]"),
        "project_path": fr.project_path,
        "run_id": run_id,
        "state": state_row.state if state_row else "untested",
        "reason": json.loads(state_row.reason_json) if state_row else {},
        "waiver_reason": waiver_row.reason if waiver_row else None,
        "waived_by": waiver_row.waived_by if waiver_row else None,
        "waiver_expires_at": waiver_row.expires_at.isoformat() if waiver_row and waiver_row.expires_at else None,
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
