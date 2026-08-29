"""Contract tests for distributing the standard repository scan workflow."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import ci_setup
from app.modules.atomic.ci_workflow_template import render_ci_workflow


def test_renderer_substitutes_one_safe_default_branch(tmp_path: Path) -> None:
    template = tmp_path / "workflow.yml"
    template.write_text("on:\n  push:\n    branches: [<default branch>]\n", encoding="utf-8")

    rendered = render_ci_workflow("release/2026.08", template_path=template)

    assert "branches: [release/2026.08]" in rendered
    assert "<default branch>" not in rendered
    assert rendered.endswith("\n")


@pytest.mark.parametrize(
    "branch",
    ("", "../main", ".hidden", "feature//one", "feature@{one", "main.lock", "main\nother"),
)
def test_renderer_rejects_unsafe_branch_names(branch: str) -> None:
    with pytest.raises(ValueError, match="default branch name is invalid"):
        render_ci_workflow(branch)


def test_bundled_workflow_is_complete_and_parseable() -> None:
    rendered = render_ci_workflow("main")
    document = yaml.safe_load(rendered)

    assert document["name"] == "assurance-scan"
    assert "ghcr.io/26457513/assurance-scan-ci:latest" in rendered
    assert "actions/upload-artifact@" in rendered
    assert "marocchino/sticky-pull-request-comment@" in rendered
    assert "assurance.sarif" in rendered
    assert "sbom.cyclonedx.json" in rendered
    assert "findings.json" in rendered


def test_route_returns_the_complete_file_and_rejects_invalid_branches() -> None:
    app = FastAPI()
    app.include_router(ci_setup.router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/ci/workflow-template", params={"default_branch": "trunk"})
    assert response.status_code == 200
    document = response.json()
    assert document["filename"] == ".github/workflows/assurance-scan.yml"
    assert document["default_branch"] == "trunk"
    assert "branches: [trunk]" in document["workflow"]

    rejected = client.get("/api/ci/workflow-template", params={"default_branch": "../main"})
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "default branch name is invalid"
