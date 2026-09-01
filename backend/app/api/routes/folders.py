"""Folder browsing endpoint. Used by the new-scan modal to let users
pick a project path by browsing instead of typing.

Scoped to the host Development folder (parent of PROJECT_ROOT) so the
server never exposes arbitrary filesystem paths.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import get_settings
from app.api.deps_project_access import ProjectAccessDep
from app.config import Settings


log = logging.getLogger(__name__)
router = APIRouter(prefix="/folders", tags=["folders"])


# Directories we hide from the picker — either noisy, huge, or non-project.
_HIDDEN_NAMES = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".idea", ".vscode", "build",
    "dist", ".next", ".cache", ".assurancescan", "target",
}


class FolderEntry(BaseModel):
    name: str
    path: str


class FoldersResponse(BaseModel):
    path: str
    root: str
    can_go_up: bool
    folders: list[FolderEntry]


def _browse_root(settings: Settings) -> Path:
    """Return the top of the browseable tree. Today that's PROJECT_ROOT's
    parent — i.e. ~/Development when the server runs against this project.
    The docker mount is `/Users/jd/Development:/Users/jd/Development`, so
    host paths line up 1:1 with container paths."""
    return settings.project_root.parent.resolve()


def _is_under(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
        return True
    except ValueError:
        return False


@router.get("", response_model=FoldersResponse)
async def list_folders(
    principal: ProjectAccessDep,
    path: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> FoldersResponse:
    """List subdirectories under `path`. If `path` is missing or outside
    the browse root, the browse root itself is listed."""
    if not principal.sees_all_projects:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="folder browsing requires an administrator")
    root = _browse_root(settings)

    if path:
        candidate = Path(path).resolve()
    else:
        candidate = root

    if not _is_under(candidate, root):
        candidate = root
    if not candidate.is_dir():
        candidate = root

    folders: list[FolderEntry] = []
    try:
        for entry in sorted(candidate.iterdir(), key=lambda e: e.name.lower()):
            if not entry.is_dir():
                continue
            if entry.name.startswith(".") or entry.name in _HIDDEN_NAMES:
                continue
            folders.append(FolderEntry(name=entry.name, path=str(entry)))
    except PermissionError as exc:
        log.warning("folder list permission denied: %s", exc)

    return FoldersResponse(
        path=str(candidate),
        root=str(root),
        can_go_up=str(candidate) != str(root),
        folders=folders,
    )
