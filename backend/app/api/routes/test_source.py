"""Test source endpoint — returns the source code for a test file.

The frontend uses this in the evidence tree to show what a test actually does
alongside its result. The file path is derived from the catalogue's
`name_pattern` (pytest-style dotted module path).

Restricted to files within the project root to prevent path traversal.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.infrastructure.db.models import Project


router = APIRouter(tags=["test-source"])


@router.get("/test-source")
async def get_test_source(
    name_pattern: str = Query(..., description="pytest-style name_pattern, e.g. tests.phase1.test_matcher::*"),
    project_id: int = Query(..., gt=0),
    session: AsyncSession = SessionDep,
) -> dict:
    """Return the source code for a test file derived from a name_pattern.

    The `name_pattern` is the dotted Python module path (`tests.phase1.test_matcher::*`).
    We split on `::`, take the module portion, replace dots with slashes, append `.py`.
    The resolved path must be inside the project's registered checkout.
    """
    if "::" in name_pattern:
        module = name_pattern.split("::", 1)[0]
    else:
        module = name_pattern
    if not module:
        raise HTTPException(status_code=400, detail="could not derive module from name_pattern")

    project = await session.get(Project, project_id)
    if project is None or project.hidden:
        raise HTTPException(status_code=404, detail="project not found")
    if project.local_path is None:
        raise HTTPException(status_code=422, detail="project has no server checkout")
    root = Path(project.local_path).resolve()
    if not root.is_dir():
        raise HTTPException(status_code=422, detail="project server checkout is unavailable")

    # Try multiple extensions. Python (pytest dotted module path) is the
    # primary case; JS/TS fall back via the same module → path derivation
    # plus common test-file extensions.
    candidates: list[tuple[str, str]] = []
    base = module.replace(".", "/")
    for ext, lang in [(".py", "python"), (".test.js", "javascript"), (".test.ts", "typescript"),
                       (".spec.js", "javascript"), (".spec.ts", "typescript"),
                       (".js", "javascript"), (".ts", "typescript"),
                       (".jsx", "javascript"), (".tsx", "typescript")]:
        candidates.append((base + ext, lang))

    full: Path | None = None
    relative_path: str | None = None
    language: str = "python"
    for rel, lang in candidates:
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            full = candidate
            relative_path = rel
            language = lang
            break

    # Patterns may be rooted at a test runner rootdir below the project root
    # (e.g. backend/). Fall back to a recursive search.
    if full is None:
        for rel, lang in candidates:
            try:
                hit = next(root.glob(f"**/{rel}"), None)
            except (ValueError, NotImplementedError):
                continue
            if hit is not None and hit.is_file():
                full = hit.resolve()
                try:
                    relative_path = str(full.relative_to(root))
                except ValueError:
                    continue
                language = lang
                break

    if full is None or relative_path is None:
        raise HTTPException(status_code=404, detail=f"test file not found for module: {module}")

    try:
        content = full.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not read file: {exc}")

    return {
        "path": relative_path,
        "language": language,
        "content": content,
        "line_count": content.count("\n") + (0 if content.endswith("\n") else 1),
    }
