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
    assert document["permissions"] == {"contents": "read", "id-token": "write"}
    assert "ghcr.io/26457513/assurance-scan-ci:latest" in rendered
    assert "ghcr.io/26457513/assurance-scan-ci-upload:latest" in rendered
    assert "persist-credentials: false" in rendered
    assert "github.event.after" in rendered
    assert "github.event.repository.default_branch" in rendered
    assert "cosign verify" in rendered
    assert "cosign verify-attestation" in rendered
    assert "signed Assurance Scan release manifest" in rendered
    assert "@$ci_digest" in rendered
    assert "@$upload_digest" in rendered
    assert "request_oidc | docker run --rm -i" in rendered
    assert "dst=/bundle,readonly" in rendered
    assert "--user 65532:65532" in rendered
    assert "actions/upload-artifact@" in rendered
    assert "retention-days: 7" in rendered
    assert "pull_request" not in rendered
    assert "workflow_dispatch" not in rendered
    assert "sticky-pull-request-comment" not in rendered
    assert "pull-requests: write" not in rendered
    assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in rendered.split("docker run --rm -i", 1)[1]
    assert "-v /var/run/docker.sock" not in rendered.split("Push result", 1)[1]


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
