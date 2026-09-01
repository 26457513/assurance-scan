"""FR list endpoint — flat matrix of all FRs for the latest catalogue (v3).

Returns each FR with: state, test count, test results summary, gap flag.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_project_access import ProjectAccessDep
from app.infrastructure.project_access import require_project
from app.state.resolver import GAP_STATES
from app.infrastructure.db.models import CatalogueSnapshot, ComplianceMapping, Fr, FrState, Run, TestResult, Waiver


router = APIRouter(tags=["frs"])


@router.get("/frs")
async def list_frs(
    principal: ProjectAccessDep,
    project_id: int = Query(...),
    snapshot_id: str | None = Query(default=None, description="specific catalogue snapshot; latest when omitted"),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Flat list of FRs for a catalogue snapshot (latest by default)."""
    if await require_project(session, principal, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    snapshot: CatalogueSnapshot | None = None
    if snapshot_id:
        snapshot = await session.get(CatalogueSnapshot, snapshot_id)
        if snapshot is not None and snapshot.project_id != project_id:
            snapshot = None
    if snapshot is None:
        snapshot_stmt = select(CatalogueSnapshot).where(
            CatalogueSnapshot.project_id == project_id
        )
        snapshot_stmt = snapshot_stmt.order_by(CatalogueSnapshot.created_at.desc()).limit(1)
        snapshot = (await session.execute(snapshot_stmt)).scalars().first()

    if snapshot is None:
        return {"frs": [], "catalogue": None, "run_id": None}

    run_stmt = (
        select(Run)
        .where(Run.project_id == snapshot.project_id)
        .order_by(Run.started_at.desc())
        .limit(1)
    )
    run = (await session.execute(run_stmt)).scalars().first()

    fr_rows = (await session.execute(
        select(Fr).where(Fr.catalogue_snapshot_id == snapshot.id).order_by(Fr.fr_id)
    )).scalars().all()

    # Pull test counts per FR from the catalogue snapshot JSON.
    snapshot_doc = json.loads(snapshot.snapshot_json)
    fr_tests_count: dict[str, int] = {
        fr["id"]: len(fr.get("tests") or [])
        for fr in snapshot_doc.get("frs", [])
    }

    state_by_fr: dict[str, str] = {}
    test_results_by_fr: dict[str, Counter] = {}
    if run:
        state_rows = (await session.execute(
            select(FrState).where(FrState.run_id == run.run_id)
        )).scalars().all()
        state_by_fr = {s.fr_id: s.state for s in state_rows}

        tr_rows = (await session.execute(
            select(TestResult).where(TestResult.run_id == run.run_id)
        )).scalars().all()
        for tr in tr_rows:
            test_results_by_fr.setdefault(tr.fr_id, Counter())[tr.result] += 1

    # Active waivers — surfaced so the UI can show *why* an FR is waived,
    # not just that it is.
    import datetime as _dt
    waiver_rows = (await session.execute(
        select(Waiver).where(Waiver.project_id == snapshot.project_id)
    )).scalars().all()
    now = _dt.datetime.now(_dt.timezone.utc)
    waiver_by_fr: dict[str, Waiver] = {}
    for w in waiver_rows:
        if w.expires_at is not None and w.expires_at <= now:
            continue
        # Most recent waiver wins if multiple exist for the same FR.
        waiver_by_fr[w.fr_id] = w

    # Derive satisfies from the compliance mapping (reverse lookup).
    satisfies_by_fr: dict[str, list[dict]] = {}
    mapping_stmt = (
        select(ComplianceMapping)
        .where(ComplianceMapping.project_id == snapshot.project_id)
        .order_by(ComplianceMapping.loaded_at.desc())
        .limit(1)
    )
    mapping_row = (await session.execute(mapping_stmt)).scalars().first()
    if mapping_row:
        mapping_doc = json.loads(mapping_row.mapping_doc_json)
        for entry in mapping_doc.get("mappings", []):
            if not entry.get("appropriate", True):
                continue
            for fr_id in entry.get("satisfied_by", []):
                satisfies_by_fr.setdefault(fr_id, []).append({
                    "ruleset": entry.get("ruleset", ""),
                    "row": entry.get("row", ""),
                })

    entries = []
    for fr in fr_rows:
        state = state_by_fr.get(fr.fr_id, "untested")
        result_counts = test_results_by_fr.get(fr.fr_id, Counter())
        waiver = waiver_by_fr.get(fr.fr_id) if state == "waived" else None
        entries.append({
            "fr_id": fr.fr_id,
            "title": fr.title,
            "category": fr.category or "",
            "state": state,
            "waiver_reason": waiver.reason if waiver else None,
            "waived_by": waiver.waived_by if waiver else None,
            "waiver_expires_at": waiver.expires_at.isoformat() if waiver and waiver.expires_at else None,
            "is_gap": state in GAP_STATES,
            "test_count": fr_tests_count.get(fr.fr_id, 0),
            "test_results": {
                "pass": result_counts.get("pass", 0),
                "fail": result_counts.get("fail", 0),
                "pending": result_counts.get("pending", 0),
            },
            "satisfies": satisfies_by_fr.get(fr.fr_id, []),
            "depends_on": json.loads(fr.depends_on_json or "[]"),
        })

    summary = {
        "total": len(entries),
        "passed": sum(1 for e in entries if e["state"] == "passed"),
        "accepted": sum(1 for e in entries if e["state"] == "accepted"),
        "failed": sum(1 for e in entries if e["state"] == "failed"),
        "pending": sum(1 for e in entries if e["state"] == "pending"),
        "untested": sum(1 for e in entries if e["state"] == "untested"),
        "waived": sum(1 for e in entries if e["state"] == "waived"),
        "blocked": sum(1 for e in entries if e["state"] == "blocked"),
        "gaps": sum(1 for e in entries if e["is_gap"]),
    }

    return {
        "catalogue": {
            "project_id": snapshot.project_id,
            "catalogue_version": snapshot.catalogue_version,
            "fr_count": len(fr_rows),
            "snapshot_id": snapshot.id,
            "created_at": snapshot.created_at.isoformat(),
        },
        "run_id": run.run_id if run else None,
        "summary": summary,
        "frs": entries,
    }
