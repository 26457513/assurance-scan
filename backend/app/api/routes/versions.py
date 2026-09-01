"""Version-listing endpoints for the dashboard's version selectors.

Catalogue snapshots and mapping snapshots are immutable multi-version
resources; these endpoints expose their history plus the available
compliance packs.
"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_project_access import ProjectAccessDep
from app.infrastructure.project_access import require_project
from app.modules.atomic.access.project_membership.service import ProjectPermission
from app.infrastructure.db.models import CatalogueSnapshot, Project
from app.infrastructure.db.repositories.compliance_mappings import ComplianceMappingRepository
from app.modules.shared.paths import RESOURCES_ROOT


router = APIRouter(tags=["versions"])

_PACK_DIR = RESOURCES_ROOT / "compliance-packs"


@router.get("/catalogue/versions")
async def list_catalogue_versions(
    principal: ProjectAccessDep,
    project_id: int = Query(..., gt=0),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """List immutable catalogue versions for one registered project."""
    await _visible_project(session, principal, project_id)

    rows = (
        await session.execute(
            sa_select(CatalogueSnapshot)
            .where(CatalogueSnapshot.project_id == project_id)
            .order_by(CatalogueSnapshot.created_at.desc())
        )
    ).scalars().all()
    return {
        "versions": [
            {
                "snapshot_id": r.id,
                "version": r.catalogue_version,
                "content_hash": r.content_hash,
                "source_commit_sha": r.source_commit_sha,
                "source_branch": r.source_branch,
                "created_at": r.created_at.isoformat(),
                "tag": r.tag,
                "project_id": r.project_id,
                "fr_count": len(json.loads(r.snapshot_json).get("frs", [])),
            }
            for r in rows
        ]
    }


@router.get("/catalogue/versions/{snapshot_id}")
async def get_catalogue_version(
    snapshot_id: str,
    principal: ProjectAccessDep,
    project_id: int = Query(..., gt=0),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """The full catalogue JSON for one snapshot."""
    snapshot = await session.get(CatalogueSnapshot, snapshot_id)
    if snapshot is None or snapshot.project_id != project_id:
        raise HTTPException(status_code=404, detail="snapshot not found")
    await _visible_project(session, principal, project_id)
    return json.loads(snapshot.snapshot_json)


@router.get("/mappings/versions")
async def list_mapping_versions(
    principal: ProjectAccessDep,
    project_id: int = Query(..., gt=0),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    await _visible_project(session, principal, project_id)
    repo = ComplianceMappingRepository(session)
    rows = await repo.list_snapshots(project_id)
    return {
        "versions": [
            {
                "snapshot_id": r.id,
                "content_hash": r.content_hash,
                "catalogue_content_hash": r.catalogue_content_hash,
                "packs": json.loads(r.packs_json or "[]"),
                "loaded_at": r.loaded_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/mappings/versions/{snapshot_id}")
async def get_mapping_version(
    snapshot_id: str,
    principal: ProjectAccessDep,
    project_id: int = Query(..., gt=0),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    repo = ComplianceMappingRepository(session)
    snapshot = await repo.get_snapshot(snapshot_id)
    if snapshot is None or snapshot.project_id != project_id:
        raise HTTPException(status_code=404, detail="snapshot not found")
    await _visible_project(session, principal, project_id)
    return json.loads(snapshot.mapping_doc_json)


class SaveMappingBody(BaseModel):
    mapping_json: str


@router.post("/mappings")
async def save_mapping(
    body: SaveMappingBody,
    principal: ProjectAccessDep,
    project_id: int = Query(..., gt=0),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Validate and store a compliance mapping for a project.

    REST mirror of the MCP save_mapping tool. Used by the Compliance
    page's paste flow.
    """
    from app.mapping import load_mapping_from_dict

    project = await _visible_project(session, principal, project_id, "manage")

    try:
        doc = json.loads(body.mapping_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc

    try:
        mapping = load_mapping_from_dict(doc, project.local_path or project.tag)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"mapping validation failed: {exc}") from exc

    repo = ComplianceMappingRepository(session)
    await repo.upsert(
        project_id=project_id,
        content_hash=mapping.content_hash,
        mapping_doc=mapping.doc,
    )
    await session.commit()
    return {
        "status": "saved",
        "project_id": project_id,
        "content_hash": mapping.content_hash,
        "mapping_count": len(mapping.doc.get("mappings", [])),
    }


async def _visible_project(
    session: AsyncSession,
    principal: ProjectAccessDep,
    project_id: int,
    permission: ProjectPermission = "view",
) -> Project:
    project = await require_project(session, principal, project_id, permission)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/compliance/packs")
async def list_compliance_packs() -> dict[str, Any]:
    """Inventory the pack directory — the multi-project regime library."""
    packs: list[dict[str, Any]] = []
    if _PACK_DIR.is_dir():
        for path in sorted(_PACK_DIR.glob("*.json")):
            # asvs-5.0.0.json → id=asvs, version=5.0.0; asvs.json → id=asvs
            match = re.match(r"^(.+?)(?:-([0-9][0-9a-zA-Z.-]*))?\.json$", path.name)
            if match is None:
                continue
            packs.append(
                {
                    "id": match.group(1).lower(),
                    "version": match.group(2) or "",
                    "file": path.name,
                }
            )
    return {"packs": packs}


@router.get("/compliance/packs/{file}")
async def get_compliance_pack(file: str) -> dict[str, Any]:
    """Return one pack document by filename (inventory-scoped, no traversal)."""
    from fastapi import HTTPException

    if "/" in file or ".." in file or not file.endswith(".json"):
        raise HTTPException(status_code=400, detail="invalid pack file")
    path = _PACK_DIR / file
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"pack {file} not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"could not read pack: {exc}")
