"""Scan endpoints: enqueue, list, get-detail."""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import QueueDep, SessionDep
from app.api.deps_project_access import ProjectAccessDep
from app.api.schemas.scan import (
    ScanRequest,
    ScanOrigin,
    ScanResponse,
    ScanStatus,
    ScanSummary,
    ScannerStatus,
)
from app.infrastructure.db.repositories.findings import FindingRepository
from app.infrastructure.db.repositories.runs import RunRepository
from app.infrastructure.db.models import Run
from app.infrastructure.db.retention import prepare_runs_for_deletion
from app.infrastructure.db.repositories.scanner_runs import ScannerRunRepository
from app.infrastructure.project_access import require_project, require_run, visible_project_ids
from app.worker.queue import ScanQueue


log = logging.getLogger(__name__)
router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("", response_model=ScanResponse, status_code=202)
async def start_scan(
    body: ScanRequest,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
    queue: ScanQueue = QueueDep,
) -> ScanResponse:
    """Enqueue a scan. Returns immediately with the run_id."""
    project = await require_project(session, principal, body.project_id, "upload")
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if project.local_path is None or not Path(project.local_path).is_dir():
        raise HTTPException(
            status_code=422,
            detail="project has no available server checkout",
        )
    options_json = json.dumps(body.options)

    runs = RunRepository(session)
    run_id = queue.enqueue(
        project_id=project.id,
        local_path=project.local_path,
        options=body.options,
    )

    run = await runs.create(
        run_id=run_id,
        project_id=project.id,
        origin="server",
        options_json=options_json,
    )
    run.repository_full_name_at_scan = project.github_repo
    await session.commit()

    return ScanResponse(
        run_id=run_id,
        project_id=project.id,
        origin="server",
        status="queued",
        queued_at=dt.datetime.now(dt.timezone.utc),
    )


@router.get("", response_model=list[ScanSummary])
async def list_scans(
    principal: ProjectAccessDep,
    project_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = SessionDep,
) -> list[ScanSummary]:
    """List recent scans with finding counts."""
    runs = RunRepository(session)
    findings = FindingRepository(session)
    if project_id is not None:
        project = await require_project(session, principal, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
    allowed_ids = await visible_project_ids(session, principal)
    rows = await runs.list_recent(
        limit=limit,
        project_id=project_id,
        project_ids=allowed_ids,
    )

    summaries: list[ScanSummary] = []
    for run in rows:
        count = await findings.count_for_run(run.run_id)
        opts = _ci_display_fields(run)
        summaries.append(
            ScanSummary(
                run_id=run.run_id,
                project_id=run.project_id,
                origin=cast(ScanOrigin, run.origin),
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                finding_count=count,
                **opts,
            )
        )
    return summaries


def _ci_display_fields(run: Run) -> dict:
    """Return source-neutral display metadata with legacy option fallbacks."""
    import json as _json

    try:
        opts = _json.loads(run.options_json or "{}")
    except ValueError:
        return {}
    fields = {
        "run_number": (
            run.local_run_number
            if run.origin == "local"
            else run.github_run_number or opts.get("run_number")
        ),
        "event": run.github_event or opts.get("event"),
        "actor": run.github_actor or opts.get("actor"),
        "display_title": (
            run.local_machine_label if run.origin == "local" else opts.get("display_title")
        ),
    }
    fields["git_branch"] = run.git_branch
    fields["commit_sha"] = run.commit_sha
    fields["working_tree_dirty"] = run.working_tree_dirty
    fields["repository"] = run.repository_full_name_at_scan
    return fields


@router.get("/{run_id}", response_model=ScanStatus)
async def get_scan(
    run_id: str,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
) -> ScanStatus:
    """Get full detail for one persisted scan and its provenance."""
    from sqlalchemy import select as sa_select

    from app.api.schemas.scan import CatalogueRef, ScanProvenance
    from app.infrastructure.db.models import CatalogueSnapshot, ComplianceMapping

    scanner_runs = ScannerRunRepository(session)

    run = await require_run(session, principal, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")

    scanner_rows = await scanner_runs.list_for_run(run_id)
    # Per-scanner wall-clock seconds live in the run payload (DB timestamps
    # are unreliable for in-process steps like tribal).
    durations: dict = {}
    if run.findings_json:
        try:
            durations = json.loads(run.findings_json).get("durations") or {}
        except ValueError:
            durations = {}
    scanner_status = [
        ScannerStatus(
            kind=r.scanner_kind,
            status=r.status,
            started_at=r.started_at,
            completed_at=r.completed_at,
            error_message=r.error_message,
            duration_seconds=durations.get(r.scanner_kind),
        )
        for r in scanner_rows
    ]

    used_snap = (
        await session.get(CatalogueSnapshot, run.catalogue_snapshot_id)
        if run.catalogue_snapshot_id
        else None
    )
    latest_snap = (
        await session.execute(
            sa_select(CatalogueSnapshot)
            .where(CatalogueSnapshot.project_id == run.project_id)
            .order_by(CatalogueSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    latest_map = (
        await session.execute(
            sa_select(ComplianceMapping)
            .where(ComplianceMapping.project_id == run.project_id)
            .order_by(ComplianceMapping.loaded_at.desc())
            .limit(1)
        )
    ).scalars().first()

    def _ref(snap) -> CatalogueRef | None:
        if snap is None:
            return None
        return CatalogueRef(
            snapshot_id=snap.id,
            version=snap.catalogue_version,
            content_hash=snap.content_hash,
        )

    provenance = ScanProvenance(
        catalogue=_ref(used_snap),
        mapping_hash=run.mapping_hash,
        current_catalogue=_ref(latest_snap),
        current_mapping_hash=latest_map.content_hash if latest_map else None,
        catalogue_stale=(
            used_snap.content_hash != latest_snap.content_hash
            if used_snap is not None and latest_snap is not None
            else None
        ),
        mapping_stale=(
            run.mapping_hash != latest_map.content_hash
            if run.mapping_hash is not None and latest_map is not None
            else None
        ),
    )

    detail_options = json.loads(run.options_json or "{}")
    if run.origin == "local":
        detail_options["run_number"] = run.local_run_number
        detail_options["display_title"] = run.local_machine_label

    return ScanStatus(
        run_id=run.run_id,
        project_id=run.project_id,
        origin=cast(ScanOrigin, run.origin),
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        scanner_status=scanner_status,
        options=detail_options,
        error_message=run.error_message,
        provenance=provenance,
        git_branch=run.git_branch,
        commit_sha=run.commit_sha,
        working_tree_dirty=run.working_tree_dirty,
        repository=run.repository_full_name_at_scan,
    )


@router.delete("/{run_id}")
async def delete_scan(
    run_id: str,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
) -> dict:
    """Delete a scan and all its related data (findings, artifacts, test
    results, FR states). Cascade deletes handle the child rows."""
    run = await require_run(session, principal, run_id, "manage")
    if run is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")
    await prepare_runs_for_deletion(session, [run_id])
    await session.delete(run)
    await session.commit()
    return {"status": "deleted", "run_id": run_id}


@router.delete("")
async def delete_all_scans(
    principal: ProjectAccessDep,
    project_id: int = Query(..., gt=0),
    session: AsyncSession = SessionDep,
) -> dict:
    """Delete all scans + project-level data (catalogue, FRs, mapping, acceptances, waivers).

    Also cleans up CatalogueSnapshot,
    ComplianceMapping, FindingAcceptance, and Waiver rows for that project —
    so a "delete all" truly resets the project to a blank state.
    """
    from sqlalchemy import select as sa_select
    from app.infrastructure.db.models import (
        CatalogueSnapshot,
        ComplianceMapping,
        ComplianceMappingSnapshot,
        FindingAcceptance,
        Waiver,
    )

    project = await require_project(session, principal, project_id, "manage")
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    stmt = sa_select(Run).where(Run.project_id == project_id)
    rows = (await session.execute(stmt)).scalars().all()
    scan_count = len(rows)
    await prepare_runs_for_deletion(session, [run.run_id for run in rows])
    for run in rows:
        await session.delete(run)

    cleaned = {}
    for model, label in [
        (CatalogueSnapshot, "catalogue_snapshots"),
        (ComplianceMapping, "compliance_mappings"),
        (ComplianceMappingSnapshot, "compliance_mapping_snapshots"),
        (FindingAcceptance, "finding_acceptances"),
        (Waiver, "waivers"),
    ]:
        project_id_column = getattr(model, "project_id")
        result = await session.execute(
            sa_select(model).where(project_id_column == project_id)
        )
        model_rows = result.scalars().all()
        for row in model_rows:
            await session.delete(row)
        if model_rows:
            cleaned[label] = len(model_rows)

    await session.commit()
    return {"status": "deleted", "scans": scan_count, "cleaned_up": cleaned}
