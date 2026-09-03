"""Contract tests for distributing the standard repository scan workflow."""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import ci_setup
from app.modules.atomic.ci_workflow_template import render_ci_workflow


def test_renderer_returns_complete_dynamic_default_branch_workflow(tmp_path: Path) -> None:
    template = tmp_path / "workflow.yml"
    template.write_text("on:\n  push:\njobs:\n  scan:\n    if: github.event.repository.default_branch", encoding="utf-8")

    rendered = render_ci_workflow(template_path=template)

    assert "github.event.repository.default_branch" in rendered
    assert rendered.endswith("\n")


def test_bundled_workflow_is_complete_and_parseable() -> None:
    rendered = render_ci_workflow()
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
    assert 'predicate = json.loads(predicate["Data"])' in rendered
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


def test_route_returns_the_complete_branch_independent_file() -> None:
    app = FastAPI()
    app.include_router(ci_setup.router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/ci/workflow-template")
    assert response.status_code == 200
    document = response.json()
    assert document["filename"] == ".github/workflows/assurance-scan.yml"
    assert document["uploader_image"] == "ghcr.io/26457513/assurance-scan-ci-upload:latest"
    assert "github.event.repository.default_branch" in document["workflow"]
    assert "branches:" not in document["workflow"]
