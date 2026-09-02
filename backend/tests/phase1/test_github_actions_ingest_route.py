"""HTTP contract tests for the disabled GitHub Actions v2 upload boundary."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.github_actions_ingest import router
from app.infrastructure.db.connection import get_session
from app.modules.atomic.access.github_oidc import GithubOidcClaims, OidcValidationError
from app.modules.workflows.github_actions_authentication import GithubActionsUploadPrincipal
from app.modules.workflows.github_oidc_ingest import (
    GithubIngestCommand,
    GithubIngestOutcome,
    GithubIngestResult,
)


FIXTURES = Path(__file__).resolve().parents[2] / "resources" / "fixtures" / "ingest-v2"
NOW = dt.datetime.now(dt.timezone.utc)
KEY = "424242:123456789:1"


def _claims() -> GithubOidcClaims:
    return GithubOidcClaims(
        subject="repo:26457513/assurance-scan:ref:refs/heads/main",
        repository_id=424242,
        repository_owner_id=26457513,
        repository="26457513/assurance-scan",
        run_id=123456789,
        run_number=26,
        run_attempt=1,
        sha="1" * 40,
        ref="refs/heads/main",
        event_name="push",
        actor="octocat",
        actor_id=583231,
        workflow_ref=(
            "26457513/assurance-scan/.github/workflows/"
            "assurance-scan.yml@refs/heads/main"
        ),
        workflow_sha="1" * 40,
        issued_at=NOW,
        not_before=NOW,
        expires_at=NOW + dt.timedelta(minutes=5),
        jti="route-test-jti",
    )


@dataclass
class FakeAuthenticator:
    tokens: list[str] = field(default_factory=list)
    authorized: int = 0
    authentication_rejection: str | None = None
    authorization_rejection: str | None = None

    async def authenticate(self, token: str, *, now: dt.datetime) -> GithubOidcClaims:
        del now
        self.tokens.append(token)
        if self.authentication_rejection:
            raise OidcValidationError(self.authentication_rejection)
        return _claims()

    async def authorize(self, claims, metadata, *, now):
        del metadata, now
        self.authorized += 1
        if self.authorization_rejection:
            raise OidcValidationError(self.authorization_rejection)
        return GithubActionsUploadPrincipal(
            project_id=7,
            github_repository_id=claims.repository_id,
            github_owner_id=claims.repository_owner_id,
            github_run_id=claims.run_id,
            github_run_attempt=claims.run_attempt,
        )


@dataclass
class FakeWorkflow:
    commands: list[GithubIngestCommand] = field(default_factory=list)

    async def ingest(self, command: GithubIngestCommand) -> GithubIngestResult:
        self.commands.append(command)
        return GithubIngestResult(
            GithubIngestOutcome.CREATED,
            "gh-424242-123456789-1",
            7,
            "26457513/assurance-scan",
            "https://scan.example.test/scans/gh-424242-123456789-1",
            "completed",
        )


@dataclass
class Harness:
    client: AsyncClient
    app: FastAPI
    authenticator: FakeAuthenticator
    workflow: FakeWorkflow


@pytest_asyncio.fixture
async def harness() -> AsyncIterator[Harness]:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        github_oidc_ingest_enabled=True,
        public_base_url="https://scan.example.test",
        github_app_id="12345",
        github_app_private_key_path="/not-used-by-test.pem",
    )
    authenticator = FakeAuthenticator()
    workflow = FakeWorkflow()
    app.state.github_actions_authenticator = authenticator
    app.state.github_actions_ingest_workflow = workflow
    app.dependency_overrides[get_session] = lambda: object()
    app.include_router(router, prefix="/api")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://scan.example.test",
    ) as client:
        yield Harness(client, app, authenticator, workflow)


def _parts():
    return [
        (
            "metadata",
            (None, (FIXTURES / "github-metadata.json").read_bytes(), "application/json; charset=utf-8"),
        ),
        (
            "findings",
            (None, (FIXTURES / "findings.json").read_bytes(), "application/json; charset=utf-8"),
        ),
        (
            "source_contexts",
            (None, (FIXTURES / "source-contexts.json").read_bytes(), "application/json; charset=utf-8"),
        ),
        ("sarif", (None, b'{"version":"2.1.0","runs":[]}', "application/sarif+json")),
    ]


async def _upload(harness: Harness, *, headers=None, files=None):
    request_headers = {"Authorization": "Bearer signed-jwt", "Idempotency-Key": KEY}
    request_headers.update(headers or {})
    return await harness.client.post(
        "/api/v2/ingest/github-actions",
        headers=request_headers,
        files=_parts() if files is None else files,
    )


def _assert_problem(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == code
    assert response.json()["retryable"] is False
    assert str(uuid.UUID(response.json()["request_id"])) == response.json()["request_id"]


async def test_disabled_endpoint_is_closed_before_authentication(harness: Harness) -> None:
    harness.app.state.settings.github_oidc_ingest_enabled = False
    response = await _upload(harness)
    assert response.status_code == 404
    assert harness.authenticator.tokens == []
    assert harness.workflow.commands == []


async def test_missing_bearer_fails_before_multipart_parsing(harness: Harness) -> None:
    response = await harness.client.post(
        "/api/v2/ingest/github-actions",
        headers={"Content-Type": "application/json"},
        content=b"not multipart",
    )
    _assert_problem(response, 401, "invalid_credential")
    assert harness.authenticator.tokens == []


async def test_valid_upload_passes_only_validated_identity_and_envelope(harness: Harness) -> None:
    response = await _upload(harness)
    assert response.status_code == 201, response.text
    assert response.json() == {
        "run_id": "gh-424242-123456789-1",
        "project_id": 7,
        "repository": {"provider": "github", "full_name": "26457513/assurance-scan"},
        "run_url": "https://scan.example.test/scans/gh-424242-123456789-1",
        "status": "completed",
        "replayed": False,
    }
    assert harness.authenticator.tokens == ["signed-jwt"]
    assert harness.authenticator.authorized == 1
    command = harness.workflow.commands[0]
    assert command.github_repository_id == 424242
    assert command.github_run_id == 123456789
    assert str(uuid.UUID(command.correlation_id)) == command.correlation_id
    assert command.envelope.metadata["schema_version"] == 2
    assert command.accepted_bytes > sum(len(item[1][1]) for item in _parts())


async def test_idempotency_key_is_bound_to_signed_claims(harness: Harness) -> None:
    response = await _upload(harness, headers={"Idempotency-Key": "424242:123456789:2"})
    _assert_problem(response, 422, "artifact_mismatch")
    assert harness.authenticator.authorized == 0
    assert harness.workflow.commands == []


async def test_oidc_rejections_are_safe_and_do_not_read_body(harness: Harness) -> None:
    harness.authenticator.authentication_rejection = "oidc_invalid"
    response = await harness.client.post(
        "/api/v2/ingest/github-actions",
        headers={"Authorization": "Bearer signed-jwt", "Idempotency-Key": KEY},
        content=b"not multipart",
    )
    _assert_problem(response, 401, "oidc_invalid")
    assert harness.authenticator.authorized == 0


async def test_workload_policy_rejections_use_frozen_problem_codes(harness: Harness) -> None:
    harness.authenticator.authorization_rejection = "non_default_branch"
    response = await _upload(harness)
    _assert_problem(response, 403, "non_default_branch")
    assert harness.authenticator.authorized == 1
    assert harness.workflow.commands == []


async def test_v2_part_media_type_and_shape_are_strict(harness: Harness) -> None:
    wrong_media = _parts()
    wrong_media[0] = (
        "metadata",
        (None, wrong_media[0][1][1], "application/json"),
    )
    media_response = await _upload(harness, files=wrong_media)
    _assert_problem(media_response, 415, "invalid_part_media_type")

    duplicate_response = await _upload(harness, files=_parts() + [_parts()[0]])
    _assert_problem(duplicate_response, 400, "duplicate_part")

    missing_response = await _upload(
        harness,
        files=[part for part in _parts() if part[0] != "source_contexts"],
    )
    _assert_problem(missing_response, 400, "unexpected_part")
    assert harness.workflow.commands == []


async def test_outer_browser_auth_never_intercepts_workload_identity() -> None:
    from app.config import load_settings
    from app.main import create_app

    settings = replace(
        load_settings(),
        app_auth_user="browser-user",
        app_auth_password="browser-password",
        github_oidc_ingest_enabled=True,
        public_base_url="https://scan.example.test",
        github_app_id="12345",
        github_app_private_key_path="/not-used-by-test.pem",
    )
    app = create_app(settings)
    authenticator = FakeAuthenticator()
    workflow = FakeWorkflow()
    app.state.github_actions_authenticator = authenticator
    app.state.github_actions_ingest_workflow = workflow
    app.dependency_overrides[get_session] = lambda: object()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://scan.example.test",
    ) as client:
        response = await client.post(
            "/api/v2/ingest/github-actions",
            headers={"Authorization": "Bearer signed-jwt", "Idempotency-Key": KEY},
            files=_parts(),
        )
    assert response.status_code == 201, response.text
    assert authenticator.tokens == ["signed-jwt"]
