"""Version-listing endpoints for the dashboard's version selectors.

Catalogue snapshots and mapping snapshots are immutable multi-version
resources; these endpoints expose their history plus the available
compliance packs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import CatalogueSnapshot
from server.db.repositories.compliance_mappings import ComplianceMappingRepository


router = APIRouter(tags=["versions"])

_PACK_DIR = Path(__file__).resolve().parents[3] / "data" / "compliance-packs"


@router.get("/catalogue/versions")
async def list_catalogue_versions(
    request: Request,
    project_path: str = Query(..., description="project identity (local path or github:repo)"),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Versions across ALL of the project's identities (registry pair +
    org-derived alias), so any selection surface shows the full list."""
    from pathlib import PurePath

    from server.db.models import Project

    identities = {project_path}
    reg = (
        await session.execute(
            sa_select(Project).where(
                (Project.local_path == project_path)
                | ("github:" + Project.github_repo == project_path)
            )
        )
    ).scalars().first()
    if reg is not None:
        identities.add(reg.local_path)
        if reg.github_repo:
            identities.add(f"github:{reg.github_repo}")
    org = request.app.state.settings.github_org
    if org and not project_path.startswith("github:"):
        identities.add(f"github:{org}/{PurePath(project_path).name}")

    rows = (
        await session.execute(
            sa_select(CatalogueSnapshot)
            .where(CatalogueSnapshot.project_path.in_(identities))
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
                "project_path": r.project_path,
                "fr_count": len(json.loads(r.snapshot_json).get("frs", [])),
            }
            for r in rows
        ]
    }


@router.get("/catalogue/versions/{snapshot_id}")
async def get_catalogue_version(snapshot_id: str, session: AsyncSession = SessionDep) -> dict[str, Any]:
    """The full catalogue JSON for one snapshot."""
    snapshot = await session.get(CatalogueSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return json.loads(snapshot.snapshot_json)


@router.get("/mappings/versions")
async def list_mapping_versions(
    project_path: str = Query(..., description="absolute project root"),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    repo = ComplianceMappingRepository(session)
    rows = await repo.list_snapshots(project_path)
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
async def get_mapping_version(snapshot_id: str, session: AsyncSession = SessionDep) -> dict[str, Any]:
    repo = ComplianceMappingRepository(session)
    snapshot = await repo.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return json.loads(snapshot.mapping_doc_json)


class SaveMappingBody(BaseModel):
    mapping_json: str


@router.post("/mappings")
async def save_mapping(
    body: SaveMappingBody,
    project_path: str = Query(...),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Validate and store a compliance mapping for a project.

    REST mirror of the MCP save_mapping tool. Used by the Compliance
    page's paste flow.
    """
    from server.mapping import load_mapping_from_dict

    try:
        doc = json.loads(body.mapping_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc

    try:
        mapping = load_mapping_from_dict(doc, project_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"mapping validation failed: {exc}") from exc

    repo = ComplianceMappingRepository(session)
    await repo.upsert(
        project_path=project_path,
        content_hash=mapping.content_hash,
        mapping_doc=mapping.doc,
    )
    await session.commit()
    return {
        "status": "saved",
        "project_path": project_path,
        "content_hash": mapping.content_hash,
        "mapping_count": len(mapping.doc.get("mappings", [])),
    }


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
