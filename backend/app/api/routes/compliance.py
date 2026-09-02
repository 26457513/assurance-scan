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

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_project_access import ProjectAccessDep
from app.infrastructure.db.models import ComplianceMapping, FrState, Run
from app.infrastructure.project_access import (
    require_project,
    shared_github_run_clause,
    visible_project_ids,
)


router = APIRouter(tags=["compliance"])


# Severity ladder (worst first). Used to derive a row's "worst" state
# from the set of FR states that satisfy it.
_SEVERITY_ORDER: tuple[str, ...] = (
    "failed",
    "pending",
    "untested",
    "blocked",
    "accepted",
    "waived",
    "passed",
)


@router.get("/compliance")
async def list_frameworks(
    principal: ProjectAccessDep,
    project_id: int | None = Query(default=None),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """List compliance frameworks that appear in any project's mapping."""
    stmt = select(ComplianceMapping)
    if project_id is not None:
        if await require_project(session, principal, project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        stmt = stmt.where(ComplianceMapping.project_id == project_id)
    else:
        allowed_ids = await visible_project_ids(session, principal)
        if allowed_ids is not None:
            stmt = stmt.where(ComplianceMapping.project_id.in_(allowed_ids))
    rows = (await session.execute(stmt.order_by(ComplianceMapping.loaded_at.desc()))).scalars().all()

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
        "frameworks": [{"id": fw, "rows": c["rows"], "frs": c["frs"]} for fw, c in sorted(framework_counts.items())]
    }


@router.get("/compliance/grid")
async def branch_compliance_grid(
    principal: ProjectAccessDep,
    project_id: int = Query(...),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Catalogue-version x branch compliance grid.

    Cell = the newest run of that branch pinned to that catalogue
    snapshot, with its FR state counts. Blank cells (absent keys) mean
    the pair has never been measured.
    """
    from app.infrastructure.db.models import CatalogueSnapshot, FrState, Run

    project = await require_project(session, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    snaps = (
        (
            await session.execute(
                select(CatalogueSnapshot)
                .where(CatalogueSnapshot.project_id == project_id)
                .order_by(CatalogueSnapshot.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    runs = (
        (
            await session.execute(
                select(Run)
                .where(
                    Run.project_id == project_id,
                    shared_github_run_clause(),
                    Run.legacy_retained.is_(False),
                    Run.catalogue_snapshot_id.isnot(None),
                    Run.git_branch.isnot(None),
                )
                .order_by(Run.started_at.desc())
            )
        )
        .scalars()
        .all()
    )

    newest: dict[str, Run] = {}
    branches: set[str] = set()
    for run in runs:  # newest first — first hit per pair wins
        if run.git_branch is None:
            continue
        branches.add(run.git_branch)
        key = f"{run.catalogue_snapshot_id}|{run.git_branch}"
        newest.setdefault(key, run)

    state_counts: dict[str, dict[str, int]] = {}
    if newest:
        from sqlalchemy import func as _func

        rows = (
            await session.execute(
                select(FrState.run_id, FrState.state, _func.count())
                .where(FrState.run_id.in_([r.run_id for r in newest.values()]))
                .group_by(FrState.run_id, FrState.state)
            )
        ).all()
        for run_id, state, n in rows:
            state_counts.setdefault(run_id, {})[state] = n

    cells = {}
    for key, run in newest.items():
        counts = state_counts.get(run.run_id, {})
        cells[key] = {
            "run_id": run.run_id,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "ok": sum(counts.get(st, 0) for st in ("passed", "accepted", "waived")),
            "gaps": sum(counts.get(st, 0) for st in ("untested", "pending", "failed", "blocked")),
            "states": counts,
        }

    return {
        "versions": [
            {
                "snapshot_id": s.id,
                "tag": s.tag,
                "version": s.catalogue_version,
                "source_branch": s.source_branch,
                "source_commit_sha": s.source_commit_sha,
                "created_at": s.created_at.isoformat(),
            }
            for s in snaps
        ],
        "branches": sorted(branches),
        "cells": cells,
    }


@router.get("/compliance/{framework}")
async def compliance_matrix(
    framework: str,
    principal: ProjectAccessDep,
    project_id: int = Query(...),
    mapping_hash: str | None = Query(default=None, description="specific mapping snapshot hash; latest when omitted"),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Return compliance-row → state matrix for one framework.

    For each row in the mapping:
      - satisfied_by: list of FR IDs from the mapping
      - state: worst state across those FRs in the latest run
      - rationale: from the mapping (agent's reasoning)
      - confidence: agent's self-assessment
    """
    if await require_project(session, principal, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    mapping_doc: dict | None = None
    mapping_project_id: int | None = None
    mapping_loaded_at = None
    resolved_hash: str | None = None

    if mapping_hash:
        # Historical mapping snapshot selected by content hash.
        from app.infrastructure.db.models import ComplianceMappingSnapshot

        snap = (
            (
                await session.execute(
                    select(ComplianceMappingSnapshot)
                    .where(
                        ComplianceMappingSnapshot.project_id == project_id,
                        ComplianceMappingSnapshot.content_hash == mapping_hash,
                    )
                    .order_by(ComplianceMappingSnapshot.loaded_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if snap is None:
            raise HTTPException(status_code=404, detail=f"no mapping snapshot with hash {mapping_hash}")
        mapping_doc = json.loads(snap.mapping_doc_json)
        mapping_project_id = snap.project_id
        mapping_loaded_at = snap.loaded_at
        resolved_hash = snap.content_hash

    if mapping_doc is None:
        mapping_stmt = select(ComplianceMapping).where(ComplianceMapping.project_id == project_id)
        mapping_stmt = mapping_stmt.order_by(ComplianceMapping.loaded_at.desc()).limit(1)
        mapping_row = (await session.execute(mapping_stmt)).scalars().first()

        if mapping_row is None:
            raise HTTPException(
                status_code=404,
                detail="no compliance mapping loaded — run a scan with fr-compliance-mapping.json present",
            )
        mapping_doc = json.loads(mapping_row.mapping_doc_json)
        mapping_project_id = mapping_row.project_id
        mapping_loaded_at = mapping_row.loaded_at
        resolved_hash = mapping_row.content_hash

    entries = [m for m in mapping_doc.get("mappings", []) if m.get("ruleset") == framework]
    if not entries:
        raise HTTPException(
            status_code=404,
            detail=f"no mapping entries for framework '{framework}'",
        )

    # Load the compliance pack to enrich rows with titles + descriptions.
    pack_data = _load_compliance_pack(framework, entries)

    # Latest run for the project (for state lookups).
    run_stmt = select(Run).where(
        Run.project_id == mapping_project_id,
        shared_github_run_clause(),
        Run.legacy_retained.is_(False),
    )
    run_stmt = run_stmt.order_by(Run.started_at.desc()).limit(1)
    run = (await session.execute(run_stmt)).scalars().first()

    # Build FR-state index for the latest run.
    state_by_fr: dict[str, str] = {}
    if run:
        state_rows = (await session.execute(select(FrState).where(FrState.run_id == run.run_id))).scalars().all()
        state_by_fr = {s.fr_id: s.state for s in state_rows}

    matrix: list[dict[str, Any]] = []
    for entry in entries:
        appropriate = entry.get("appropriate", True)
        row_id = entry["row"]
        pack_info = pack_data.get(row_id, {})
        fr_ids = entry.get("satisfied_by", [])
        if not appropriate:
            worst = "n/a"
            fr_states: dict[str, str] = {}
        else:
            fr_state_values = [state_by_fr.get(fid, "untested") for fid in fr_ids]
            worst = _worst_state(fr_state_values)
            fr_states = dict(zip(fr_ids, fr_state_values))
        matrix.append(
            {
                "row_id": row_id,
                "title": pack_info.get("title", row_id),
                "description": pack_info.get("description", ""),
                "section": pack_info.get("section", ""),
                "level": pack_info.get("level", ""),
                "version": entry.get("version"),
                "appropriate": appropriate,
                "fr_ids": fr_ids,
                "fr_states": fr_states,
                "worst_state": worst,
                "rationale": entry.get("rationale", ""),
                "confidence": entry.get("confidence", "medium"),
            }
        )

    matrix.sort(key=lambda e: e["row_id"])

    summary: dict[str, int] = defaultdict(int)
    for entry in matrix:
        summary[entry["worst_state"]] += 1

    return {
        "framework": framework,
        "project_id": mapping_project_id,
        "mapping_loaded_at": mapping_loaded_at.isoformat() if mapping_loaded_at else None,
        "mapping_hash": resolved_hash,
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


_PACK_CACHE: dict[str, dict[str, Any]] = {}


def _load_compliance_pack(
    framework: str,
    entries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Load the compliance pack JSON and return {row_id: {title, description, ...}}.

    Looks for the pack at backend/resources/compliance-packs/<framework>-<version>.json.
    Caches per framework to avoid re-reading on every request.
    """
    # Determine version from the entries (all should be same version).
    version = None
    for e in entries:
        if e.get("version"):
            version = e["version"]
            break

    cache_key = f"{framework}:{version or 'any'}"
    if cache_key in _PACK_CACHE:
        return _PACK_CACHE[cache_key]

    from app.modules.shared.paths import RESOURCES_ROOT

    pack_dir = RESOURCES_ROOT / "compliance-packs"
    # Try versioned filename first, then unversioned.
    candidates = []
    if version:
        candidates.append(pack_dir / f"{framework.lower()}-{version}.json")
    candidates.append(pack_dir / f"{framework.lower()}.json")

    rows_by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if candidate.exists():
            try:
                pack = json.loads(candidate.read_text(encoding="utf-8"))
                for row in pack.get("rows", []):
                    rows_by_id[row["row"]] = row
                break
            except (OSError, json.JSONDecodeError):
                pass

    _PACK_CACHE[cache_key] = rows_by_id
    return rows_by_id
