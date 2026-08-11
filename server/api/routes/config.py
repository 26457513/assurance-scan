"""Config viewer endpoint — returns the three raw JSON config files.

GET /api/config?project_path=...

Returns the FR catalogue, compliance mapping, and compliance pack(s) as raw
JSON documents so the user can inspect the exact configuration driving a scan.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep


router = APIRouter(tags=["config"])

# Where compliance packs live — checked relative to the app root first,
# then relative to the project (for dev mode where data/ is in the bind-mount).
_PACK_DIR_APP = Path(__file__).resolve().parents[3] / "data" / "compliance-packs"


@router.get("/config")
async def get_config(
    project_path: str = Query(..., description="absolute project root"),
    session: AsyncSession = SessionDep,
) -> dict[str, Any]:
    """Return the three config files as raw JSON for inspection."""
    root = Path(project_path).resolve()

    result: dict[str, Any] = {}

    # 1. FR catalogue
    catalogue_path = root / "fr-catalog.json"
    result["catalogue"] = _read_json(catalogue_path, root, "fr-catalog.json")

    # 2. Compliance mapping
    mapping_path = root / "fr-compliance-mapping.json"
    result["mapping"] = _read_json(mapping_path, root, "fr-compliance-mapping.json")

    # 3. Compliance pack(s) — determined by which rulesets appear in the mapping
    packs: dict[str, Any] = {}
    if result["mapping"] and isinstance(result["mapping"], dict):
        seen = set()
        for entry in result["mapping"].get("mappings", []):
            ruleset = entry.get("ruleset", "")
            version = entry.get("version", "")
            key = f"{ruleset}:{version}" if version else ruleset
            if key in seen or not ruleset:
                continue
            seen.add(key)
            pack = _load_pack(ruleset, version)
            if pack is not None:
                packs[ruleset] = pack
    result["compliance_packs"] = packs

    return result


def _read_json(path: Path, root: Path, label: str) -> dict | None:
    """Read a JSON file, guarding against path traversal."""
    try:
        path.resolve().relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail=f"{label}: path outside project root")
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"{label}: {exc}")


def _load_pack(framework: str, version: str | None) -> dict | None:
    """Load a compliance pack JSON. Tries app-embedded copy first, then project."""
    for base in (_PACK_DIR_APP,):
        candidates = []
        if version:
            candidates.append(base / f"{framework.lower()}-{version}.json")
        candidates.append(base / f"{framework.lower()}.json")
        for candidate in candidates:
            if candidate.is_file():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
    return None
