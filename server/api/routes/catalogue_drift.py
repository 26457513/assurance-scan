"""Catalogue drift check — is the current catalogue still valid for the codebase?

Deterministic, LLM-free validation of the project's latest catalogue snapshot:
  - every FR `implemented_by` ref still exists on disk
  - every unit-test `name_pattern` still resolves to a test file
  - the codebase commit vs the commit the catalogue was generated against

Evaluated at view time against the mounted project folder.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.deps import SessionDep
from server.db.models import CatalogueSnapshot
from server.vcs import git_head


router = APIRouter(prefix="/catalogue", tags=["catalogue"])

_EXTENSIONS = (".py", ".test.js", ".test.ts", ".spec.js", ".spec.ts", ".js", ".ts", ".jsx", ".tsx")


class MissingFile(BaseModel):
    fr_id: str
    ref: str


class UnresolvedPattern(BaseModel):
    fr_id: str
    test_id: str
    name_pattern: str


class DriftResponse(BaseModel):
    project_path: str
    status: str = "ok"
    reason: str | None = None
    catalogue_snapshot_id: str | None = None
    catalogue_version: str | None = None
    catalogue_content_hash: str | None = None
    snapshot_commit: str | None = None
    current_commit: str | None = None
    code_moved: bool | None = None
    missing_files: list[MissingFile] = []
    unresolved_patterns: list[UnresolvedPattern] = []
    drifted_fr_ids: list[str] = []


def _module_resolves(root: Path, name_pattern: str) -> bool:
    """True when a pytest-style name_pattern maps to an existing test file.

    Patterns are rooted at the test runner's rootdir, which may sit below the
    project root (e.g. `backend/`), so a direct path miss falls back to a
    recursive `**/` glob. Glob segments (`tests.unit.*.test_x::*`) are
    handled by the same glob.
    """
    module = name_pattern.split("::", 1)[0] if "::" in name_pattern else name_pattern
    if not module:
        return False
    base = module.replace(".", "/")
    for ext in _EXTENSIONS:
        candidate = (root / (base + ext)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            return True
    for ext in _EXTENSIONS:
        try:
            if next(root.glob(f"**/{base}{ext}"), None) is not None:
                return True
        except (ValueError, NotImplementedError):
            continue
    return False


def _ref_exists(root: Path, ref: str) -> bool:
    candidate = (root / ref).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return candidate.exists()


@router.get("/drift", response_model=DriftResponse)
async def get_catalogue_drift(
    project_path: str = Query(..., description="absolute project root"),
    session: AsyncSession = SessionDep,
) -> DriftResponse:
    root = Path(project_path).resolve()
    if project_path.startswith("github:"):
        # Remote identity: no local working tree to diff against — drift is
        # undefined for projects whose code lives on GitHub only.
        return DriftResponse(
            project_path=project_path,
            status="unavailable",
            reason="remote project (no local working tree)",
        )
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"project path not found: {project_path}")

    snapshot = (
        await session.execute(
            sa_select(CatalogueSnapshot)
            .where(CatalogueSnapshot.project_path == project_path)
            .order_by(CatalogueSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"no catalogue snapshot for {project_path}")

    doc = json.loads(snapshot.snapshot_json)
    missing_files: list[MissingFile] = []
    unresolved: list[UnresolvedPattern] = []
    drifted: set[str] = set()

    for fr in doc.get("frs", []):
        fr_id = fr.get("id", "?")
        for ref in fr.get("implemented_by", []) or []:
            ref_path = ref.get("ref") if isinstance(ref, dict) else None
            if ref_path and not _ref_exists(root, ref_path):
                missing_files.append(MissingFile(fr_id=fr_id, ref=ref_path))
                drifted.add(fr_id)
        for test in fr.get("tests", []) or []:
            if test.get("type") != "unit-test":
                continue
            pattern = test.get("name_pattern")
            if pattern and not _module_resolves(root, pattern):
                unresolved.append(
                    UnresolvedPattern(
                        fr_id=fr_id,
                        test_id=test.get("id", "?"),
                        name_pattern=pattern,
                    )
                )
                drifted.add(fr_id)

    current_commit = await git_head(project_path)
    snapshot_commit = snapshot.source_commit_sha
    code_moved = (
        snapshot_commit != current_commit
        if snapshot_commit is not None and current_commit is not None
        else None
    )

    return DriftResponse(
        project_path=project_path,
        catalogue_snapshot_id=snapshot.id,
        catalogue_version=snapshot.catalogue_version,
        catalogue_content_hash=snapshot.content_hash,
        snapshot_commit=snapshot_commit,
        current_commit=current_commit,
        code_moved=code_moved,
        missing_files=missing_files,
        unresolved_patterns=unresolved,
        drifted_fr_ids=sorted(drifted),
    )
