"""Distribution endpoint for the self-contained GitHub Actions workflow."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.atomic.ci_workflow_template import render_ci_workflow


router = APIRouter(prefix="/ci", tags=["ci-setup"])


@router.get("/workflow-template")
async def get_ci_workflow_template() -> dict[str, str]:
    return {
        "filename": ".github/workflows/assurance-scan.yml",
        "image": "ghcr.io/26457513/assurance-scan-ci:latest",
        "uploader_image": "ghcr.io/26457513/assurance-scan-ci-upload:latest",
        "workflow": render_ci_workflow(),
    }
