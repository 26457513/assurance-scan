"""Scan endpoints: enqueue, list, get-detail."""
from __future__ import annotations

import datetime as dt
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep, QueueDep, get_settings
from server.api.schemas.scan import (
    ScanRequest,
    ScanResponse,
    ScanStatus,
    ScanSummary,
    ScannerStatus,
)
from server.db.repositories.findings import FindingRepository
from server.db.repositories.runs import RunRepository
from server.db.models import Run
from server.db.repositories.scanner_runs import ScannerRunRepository
from server.worker.queue import ScanQueue


log = logging.getLogger(__name__)
router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("", response_model=ScanResponse, status_code=202)
async def start_scan(
    body: ScanRequest,
    session: AsyncSession = SessionDep,
    queue: ScanQueue = QueueDep,
    settings=Depends(get_settings),
) -> ScanResponse:
    """Enqueue a scan. Returns immediately with the run_id."""
    project_path = body.project_path or str(settings.project_root)
    options_json = json.dumps(body.options)

    runs = RunRepository(session)
    run_id = queue.enqueue(project_path=project_path, options=body.options)

    await runs.create(
        run_id=run_id,
        project_path=project_path,
        options_json=options_json,
    )
    await session.commit()

    return ScanResponse(
        run_id=run_id,
        project_path=project_path,
        status="queued",
        queued_at=dt.datetime.now(dt.timezone.utc),
    )


@router.get("", response_model=list[ScanSummary])
async def list_scans(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = SessionDep,
) -> list[ScanSummary]:
    """List recent scans with finding counts."""
    runs = RunRepository(session)
    findings = FindingRepository(session)
    rows = await runs.list_recent(limit=limit)

    summaries: list[ScanSummary] = []
    for run in rows:
        count = await findings.count_for_run(run.run_id)
        opts = _ci_display_fields(run)
        summaries.append(
            ScanSummary(
                run_id=run.run_id,
                project_path=run.project_path,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                finding_count=count,
                **opts,
            )
        )
    return summaries


def _ci_display_fields(run: Run) -> dict:
    """GitHub run display metadata from options_json (empty for local runs)."""
    import json as _json

    if not run.run_id.startswith("gh-"):
        return {}
    try:
        opts = _json.loads(run.options_json or "{}")
    except ValueError:
        return {}
    fields = {
        k: opts.get(k)
        for k in ("run_number", "event", "actor", "display_title")
    }
    fields["git_branch"] = run.git_branch
    return fields


@router.get("/{run_id}", response_model=ScanStatus)
async def get_scan(run_id: str, request: Request, session: AsyncSession = SessionDep) -> ScanStatus:
    """Get full detail for one scan, including per-scanner status + provenance.

    A gh- run that isn't ingested yet (link clicked before the poller cycle)
    triggers one on-demand poll so deep links work immediately.
    """
    from sqlalchemy import select as sa_select

    if await RunRepository(session).get(run_id) is None and run_id.startswith("gh-"):
        settings = request.app.state.settings
        if settings.github_poll_token:
            from server.db.connection import get_sessionmaker
            from server.github_poller import GitHubClient, poll_cycle, resolve_repos

            client = GitHubClient(settings.github_poll_token)
            repos = resolve_repos(client, settings.poll_repos, settings.github_org)
            await poll_cycle(get_sessionmaker(settings), client, repos)

    from server.api.schemas.scan import CatalogueRef, ScanProvenance
    from server.db.models import CatalogueSnapshot, ComplianceMapping

    runs = RunRepository(session)
    scanner_runs = ScannerRunRepository(session)

    run = await runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")

    scanner_rows = await scanner_runs.list_for_run(run_id)
    scanner_status = [
        ScannerStatus(
            kind=r.scanner_kind,
            status=r.status,
            started_at=r.started_at,
            completed_at=r.completed_at,
            error_message=r.error_message,
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
            .where(CatalogueSnapshot.project_path == run.project_path)
            .order_by(CatalogueSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    latest_map = (
        await session.execute(
            sa_select(ComplianceMapping)
            .where(ComplianceMapping.project_path == run.project_path)
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

    return ScanStatus(
        run_id=run.run_id,
        project_path=run.project_path,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        scanner_status=scanner_status,
        options=json.loads(run.options_json or "{}"),
        error_message=run.error_message,
        provenance=provenance,
        git_branch=run.git_branch,
        commit_sha=run.commit_sha,
    )


@router.delete("/{run_id}")
async def delete_scan(run_id: str, session: AsyncSession = SessionDep) -> dict:
    """Delete a scan and all its related data (findings, artifacts, test
    results, FR states). Cascade deletes handle the child rows."""
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")
    await session.delete(run)
    await session.commit()
    return {"status": "deleted", "run_id": run_id}


@router.delete("")
async def delete_all_scans(
    project_path: str | None = Query(default=None),
    session: AsyncSession = SessionDep,
) -> dict:
    """Delete all scans + project-level data (catalogue, FRs, mapping, acceptances, waivers).

    When project_path is given, also cleans up CatalogueSnapshot, Fr,
    ComplianceMapping, FindingAcceptance, and Waiver rows for that project —
    so a "delete all" truly resets the project to a blank state.
    """
    from sqlalchemy import select as sa_select
    from server.db.models import (
        CatalogueSnapshot, ComplianceMapping, FindingAcceptance, Fr, Waiver,
    )

    stmt = sa_select(Run)
    if project_path:
        stmt = stmt.where(Run.project_path == project_path)
    rows = (await session.execute(stmt)).scalars().all()
    scan_count = len(rows)
    for run in rows:
        await session.delete(run)

    # Clean up project-level data when a specific project is targeted.
    cleaned = {}
    if project_path:
        for model, label in [
            (CatalogueSnapshot, "catalogue_snapshots"),
            (Fr, "frs"),
            (ComplianceMapping, "compliance_mappings"),
            (FindingAcceptance, "finding_acceptances"),
            (Waiver, "waivers"),
        ]:
            result = await session.execute(
                sa_select(model).where(model.project_path == project_path)
            )
            model_rows = result.scalars().all()
            for row in model_rows:
                await session.delete(row)
            if model_rows:
                cleaned[label] = len(model_rows)

    await session.commit()
    return {"status": "deleted", "scans": scan_count, "cleaned_up": cleaned}
