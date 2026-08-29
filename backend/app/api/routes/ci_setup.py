"""Distribution endpoint for the self-contained GitHub Actions workflow."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.modules.atomic.ci_workflow_template import render_ci_workflow


router = APIRouter(prefix="/ci", tags=["ci-setup"])


@router.get("/workflow-template")
async def get_ci_workflow_template(
    default_branch: str = Query(default="main", min_length=1, max_length=255),
) -> dict[str, str]:
    try:
        workflow = render_ci_workflow(default_branch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "filename": ".github/workflows/assurance-scan.yml",
        "default_branch": default_branch.strip(),
        "image": "ghcr.io/26457513/assurance-scan-ci:latest",
        "workflow": workflow,
    }
