"""Config viewer endpoint — returns the config artefacts driving a scan.

GET /api/config?project_id=...

Returns the FR catalogue and compliance mapping from the DB (both are
DB-resident; every load path — MCP save, scan-time file load — stores a
snapshot/row), plus the compliance pack(s) referenced by the mapping.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.infrastructure.db.models import CatalogueSnapshot, ComplianceMapping, Project
from app.modules.shared.paths import RESOURCES_ROOT


router = APIRouter(tags=["config"])

# Where compliance packs live (multi-project resources shipped with the app).
_PACK_DIR_APP = RESOURCES_ROOT / "compliance-packs"


@router.get("/config")
async def get_config(
    project_id: int = Query(..., gt=0),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Return the catalogue, mapping, and referenced packs for inspection."""
    project = await session.get(Project, project_id)
    if project is None or project.hidden:
        raise HTTPException(status_code=404, detail="project not found")
    snapshot = (
        await session.execute(
            sa_select(CatalogueSnapshot)
            .where(CatalogueSnapshot.project_id == project_id)
            .order_by(CatalogueSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    catalogue = json.loads(snapshot.snapshot_json) if snapshot else None

    mapping_row = (
        await session.execute(
            sa_select(ComplianceMapping)
            .where(ComplianceMapping.project_id == project_id)
            .order_by(ComplianceMapping.loaded_at.desc())
            .limit(1)
        )
    ).scalars().first()
    mapping = json.loads(mapping_row.mapping_doc_json) if mapping_row else None

    packs: dict[str, Any] = {}
    if isinstance(mapping, dict):
        seen = set()
        for entry in mapping.get("mappings", []):
            ruleset = entry.get("ruleset", "")
            version = entry.get("version", "")
            key = f"{ruleset}:{version}" if version else ruleset
            if key in seen or not ruleset:
                continue
            seen.add(key)
            pack = _load_pack(ruleset, version)
            if pack is not None:
                packs[ruleset] = pack

    return {"catalogue": catalogue, "mapping": mapping, "compliance_packs": packs}


def _load_pack(framework: str, version: str | None) -> dict | None:
    """Load a compliance pack JSON by ruleset (+optional version)."""
    candidates = []
    if version:
        candidates.append(_PACK_DIR_APP / f"{framework.lower()}-{version}.json")
    candidates.append(_PACK_DIR_APP / f"{framework.lower()}.json")
    for candidate in candidates:
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
    return None
