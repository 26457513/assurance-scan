"""Focused protocol tests for the version-one local-ingest HTTP boundary."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.routes import local_ingest
from app.api.deps_scan_token import require_scan_token_principal
from app.api.routes.local_ingest import get_local_scan_ingest_workflow, router
from app.api.schemas.local_ingest import (
    LocalScanIngestCommand,
    LocalScanIngestOutcome,
    LocalScanIngestResult,
)
from app.modules.atomic.access.scan_token import ScanTokenPrincipal
from app.modules.shared.contracts.local_scan import UPLOAD_LIMITS, UploadLimits


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "local-scan"
IDEMPOTENCY_KEY = "018f47a2-4c72-4c9e-9f60-780cb70b8fe4"


@dataclass
class FakeWorkflow:
    commands: list[LocalScanIngestCommand]

    async def ingest_local_scan(self, command: LocalScanIngestCommand) -> LocalScanIngestResult:
        self.commands.append(command)
        return LocalScanIngestResult(
            outcome=LocalScanIngestOutcome.CREATED,
            run_id="local-123",
            project_id=42,
            repository=str(command.metadata["repository"]),
            run_url="https://scan.example.test/scans/local-123",
            status="completed",
        )


@dataclass
class RouteHarness:
    client: AsyncClient
    workflow: FakeWorkflow
    app: FastAPI


def _principal() -> ScanTokenPrincipal:
    return ScanTokenPrincipal(
        token_id="token-id",
        user_id=7,
        account_name="alice@example.test",
        token_label="laptop",
        scope="scans:upload",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )


@pytest_asyncio.fixture
async def harness() -> RouteHarness:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        local_ingest_enabled=True,
        github_app_client_id="client",
        github_app_client_secret="secret",
        token_encryption_key="encryption-key",
        session_secret="session-secret-at-least-32-bytes-long",
        public_base_url="https://scan.example.test",
        local_ingest_repository_allowlist=frozenset(),
    )
    workflow = FakeWorkflow(commands=[])
    app.include_router(router, prefix="/api")
    app.dependency_overrides[require_scan_token_principal] = _principal
    app.dependency_overrides[get_local_scan_ingest_workflow] = lambda: workflow
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://scan.example.test",
    ) as client:
        yield RouteHarness(client=client, workflow=workflow, app=app)


def _valid_parts(
    *,
    metadata: bytes | None = None,
    findings: bytes | None = None,
) -> list[tuple[str, tuple[str | None, bytes, str]]]:
    return [
        (
            "metadata",
            (
                None,
                metadata or (FIXTURES / "valid" / "metadata.json").read_bytes(),
                "application/json",
            ),
        ),
        (
            "findings",
            (
                "findings.json",
                findings or (FIXTURES / "valid" / "findings.json").read_bytes(),
                "application/json",
            ),
        ),
    ]


async def _upload(
    client: AsyncClient,
    *,
    files: list[tuple[str, tuple[str | None, bytes, str]]] | None = None,
    key: str = IDEMPOTENCY_KEY,
):
    return await client.post(
        "/api/v1/ingest/local-scans",
        files=files or _valid_parts(),
        headers={"Idempotency-Key": key},
    )


def _assert_problem(response, *, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"].endswith(code.replace("_", "-"))
    assert body["instance"].startswith("/api/v1/ingest/")
    assert isinstance(body["retryable"], bool)
    assert isinstance(body["request_id"], str)
    assert isinstance(body["limits"], dict)
    return body


async def test_capabilities_and_whoami_require_token_and_advertise_v1(
    harness: RouteHarness,
) -> None:
    capabilities = await harness.client.get("/api/v1/ingest/capabilities")
    whoami = await harness.client.get("/api/v1/ingest/whoami")
    assert capabilities.status_code == 200
    assert capabilities.json()["supported_schema_versions"] == [1]
    assert capabilities.json()["limits"]["wire_bytes"] == UPLOAD_LIMITS.wire_bytes
    assert whoami.json()["account"] == "alice@example.test"
    assert whoami.json()["token_label"] == "laptop"
    assert whoami.json()["scopes"] == ["scans:upload"]


async def test_capabilities_advertise_operator_lowered_limits(harness: RouteHarness) -> None:
    harness.app.state.settings.local_ingest_upload_limits = replace(
        UPLOAD_LIMITS,
        wire_bytes=1024,
        findings_count=10,
    )

    response = await harness.client.get("/api/v1/ingest/capabilities")

    assert response.json()["limits"]["wire_bytes"] == 1024
    assert response.json()["limits"]["findings_count"] == 10


async def test_feature_disabled_fails_closed_before_workflow(harness: RouteHarness) -> None:
    harness.app.state.settings.local_ingest_enabled = False
    response = await _upload(harness.client)
    _assert_problem(response, status=503, code="local_ingest_disabled")
    assert harness.workflow.commands == []


async def test_feature_fails_closed_without_account_bound_github_identity(
    harness: RouteHarness,
) -> None:
    harness.app.state.settings.github_app_client_id = ""
    response = await _upload(harness.client)
    _assert_problem(response, status=503, code="local_ingest_disabled")
    assert harness.workflow.commands == []


@pytest.mark.parametrize(
    ("status", "detail", "code"),
    [(401, "invalid bearer credential", "invalid_credential"), (403, "scope", "insufficient_scope")],
)
async def test_authentication_failures_are_uniform_problem_details(
    harness: RouteHarness,
    status: int,
    detail: str,
    code: str,
) -> None:
    async def reject() -> None:
        raise HTTPException(status_code=status, detail=detail)

    harness.app.dependency_overrides[require_scan_token_principal] = reject
    response = await harness.client.get("/api/v1/ingest/whoami")
    body = _assert_problem(response, status=status, code=code)
    assert detail not in body["detail"].lower()


async def test_only_upload_rejections_emit_correlated_request_signals(
    harness: RouteHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def reject() -> None:
        raise HTTPException(status_code=401, detail="secret credential value")

    harness.app.dependency_overrides[require_scan_token_principal] = reject
    caplog.set_level(logging.INFO, logger="app.api.routes.local_ingest")

    whoami = await harness.client.get("/api/v1/ingest/whoami")
    assert whoami.status_code == 401
    assert not [record for record in caplog.records if '"event":"ingest_request"' in record.message]

    upload = await _upload(harness.client)
    signals = [json.loads(record.message) for record in caplog.records if '"event":"ingest_request"' in record.message]
    assert len(signals) == 1
    assert signals[0]["origin"] == "local"
    assert signals[0]["code"] == "invalid_credential"
    assert signals[0]["correlation_id"] == upload.json()["request_id"]
    assert "secret credential value" not in caplog.text


async def test_valid_upload_calls_narrow_workflow_with_validated_bundle(
    harness: RouteHarness,
) -> None:
    response = await _upload(harness.client)
    assert response.status_code == 201, response.text
    body = response.json()
    request_id = body.pop("request_id")
    assert str(uuid.UUID(request_id)) == request_id
    assert body == {
        "run_id": "local-123",
        "project_id": 42,
        "repository": {"provider": "github", "full_name": "26457513/assurance-scan"},
        "run_url": "https://scan.example.test/scans/local-123",
        "status": "completed",
        "replayed": False,
    }
    command = harness.workflow.commands[0]
    assert command.idempotency_key == IDEMPOTENCY_KEY
    assert str(uuid.UUID(command.correlation_id)) == command.correlation_id
    assert command.correlation_id == request_id
    assert command.principal.user_id == 7
    assert command.accepted_bytes > len(command.findings_bytes)
    assert command.payload_hash and len(command.payload_hash) == 64
    assert command.sarif_bytes is None and command.sbom_bytes is None


async def test_upload_signal_reports_counts_without_secret_or_host_path(
    harness: RouteHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "AS_CANARY_SECRET_DO_NOT_PERSIST_signal"
    host_path = "/Users/private-user/source/app.py"
    findings = json.loads((FIXTURES / "valid" / "findings.json").read_text())
    findings["findings"][0]["message"] = f"{canary} at {host_path}"
    caplog.set_level(logging.INFO, logger="app.api.routes.local_ingest")

    response = await _upload(
        harness.client,
        files=_valid_parts(findings=json.dumps(findings).encode()),
    )

    assert response.status_code == 201
    signals = [json.loads(record.message) for record in caplog.records if '"event":"ingest_request"' in record.message]
    assert signals == [
        {
            "origin": "local",
            "code": "scan_created",
            "correlation_id": signals[0]["correlation_id"],
            "duration_ms": signals[0]["duration_ms"],
            "event": "ingest_request",
            "finding_count": 1,
            "outcome": "created",
            "project_id": 42,
            "redaction_count": 2,
            "replayed": False,
            "scanner_count": 1,
            "status_code": 201,
            "wire_bytes": signals[0]["wire_bytes"],
        }
    ]
    rendered = json.dumps(signals)
    assert canary not in rendered
    assert host_path not in rendered
    assert "26457513/assurance-scan" not in rendered


async def test_canary_allowlist_blocks_other_repositories_without_echoing_identity(
    harness: RouteHarness,
) -> None:
    harness.app.state.settings.local_ingest_repository_allowlist = frozenset({"other/repository"})
    response = await _upload(harness.client)
    body = _assert_problem(response, status=403, code="repository_not_enabled")
    assert "26457513/assurance-scan" not in response.text
    assert body["retryable"] is False
    assert harness.workflow.commands == []


async def test_canary_allowlist_uses_effective_project_override(
    harness: RouteHarness,
) -> None:
    harness.app.state.settings.local_ingest_repository_allowlist = frozenset({"26457513/assurance-scan"})
    metadata = json.loads((FIXTURES / "valid" / "metadata.json").read_text())
    metadata["repository"] = "developer/assurance-scan-fork"
    metadata["project_override"] = "26457513/assurance-scan"

    response = await _upload(
        harness.client,
        files=_valid_parts(metadata=json.dumps(metadata).encode()),
    )

    assert response.status_code == 201, response.text
    assert harness.workflow.commands[0].metadata["repository"] == "developer/assurance-scan-fork"


async def test_request_status_endpoint_is_owned_and_returns_durable_state(
    harness: RouteHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.db.connection import get_session
    from app.infrastructure.local_scan_ingest import LocalRequestStatus
    import app.infrastructure.local_scan_ingest as composition

    async def fake_status(_session, *, user_id: int, request_id: str):
        assert user_id == 7
        assert request_id == IDEMPOTENCY_KEY
        return LocalRequestStatus(
            state="completed",
            run_id="local-123",
            project_id=42,
            repository="26457513/assurance-scan",
            lease_expires_at=None,
        )

    harness.app.dependency_overrides[get_session] = lambda: object()
    monkeypatch.setattr(composition, "get_local_request_status", fake_status)
    response = await harness.client.get(f"/api/v1/ingest/local-scans/requests/{IDEMPOTENCY_KEY}")

    assert response.status_code == 200
    assert response.json()["run_id"] == "local-123"
    assert response.json()["repository"]["full_name"] == "26457513/assurance-scan"


async def test_rejects_missing_or_mismatched_idempotency_key(harness: RouteHarness) -> None:
    missing = await harness.client.post("/api/v1/ingest/local-scans", files=_valid_parts())
    mismatch = await _upload(harness.client, key="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    _assert_problem(missing, status=400, code="invalid_idempotency_key")
    _assert_problem(mismatch, status=400, code="idempotency_key_mismatch")


async def test_rejects_wrong_outer_and_part_media_types(harness: RouteHarness) -> None:
    outer = await harness.client.post(
        "/api/v1/ingest/local-scans",
        content=b"{}",
        headers={"Content-Type": "application/json", "Idempotency-Key": IDEMPOTENCY_KEY},
    )
    parts = _valid_parts()
    parts[0] = ("metadata", (None, parts[0][1][1], "text/plain"))
    part = await _upload(harness.client, files=parts)
    _assert_problem(outer, status=415, code="unsupported_media_type")
    _assert_problem(part, status=415, code="unsupported_part_media_type")


async def test_rejects_duplicate_unknown_and_missing_parts(harness: RouteHarness) -> None:
    duplicate = await _upload(harness.client, files=_valid_parts() + [_valid_parts()[0]])
    unknown = await _upload(
        harness.client,
        files=_valid_parts() + [("source", ("source.zip", b"PK\x03\x04", "application/zip"))],
    )
    missing = await _upload(harness.client, files=_valid_parts()[0:1])
    for response in (duplicate, unknown, missing):
        _assert_problem(response, status=400, code="invalid_multipart_parts")


async def test_rejects_duplicate_json_keys_and_excessive_depth(harness: RouteHarness) -> None:
    duplicate = (FIXTURES / "invalid" / "metadata-duplicate-key.json").read_bytes()
    duplicate_response = await _upload(harness.client, files=_valid_parts(metadata=duplicate))
    deep_findings = json.dumps(
        {"schema_version": 1, "scanners": [], "findings": [], "deep": [[[[[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]]]]]},
    ).encode()
    depth_response = await _upload(harness.client, files=_valid_parts(findings=deep_findings))
    _assert_problem(duplicate_response, status=400, code="duplicate_json_key")
    _assert_problem(depth_response, status=422, code="json_depth_exceeded")


async def test_rejects_unsupported_version_and_schema_violation(harness: RouteHarness) -> None:
    unsupported = (FIXTURES / "invalid" / "metadata-unsupported-version.json").read_bytes()
    version_response = await _upload(harness.client, files=_valid_parts(metadata=unsupported))
    metadata = json.loads((FIXTURES / "valid" / "metadata.json").read_text())
    metadata["origin"] = "github"
    schema_response = await _upload(
        harness.client,
        files=_valid_parts(metadata=json.dumps(metadata).encode()),
    )
    body = _assert_problem(version_response, status=422, code="unsupported_schema_version")
    assert body["supported_schema_versions"] == [1]
    _assert_problem(schema_response, status=422, code="schema_validation_failed")


async def test_rejects_declared_and_streamed_oversize_before_workflow(harness: RouteHarness) -> None:
    declared = await harness.client.post(
        "/api/v1/ingest/local-scans",
        content=b"",
        headers={
            "Content-Type": "multipart/form-data; boundary=x",
            "Content-Length": str(UPLOAD_LIMITS.wire_bytes + 1),
            "Idempotency-Key": IDEMPOTENCY_KEY,
        },
    )
    oversized_metadata = b"{" + b" " * UPLOAD_LIMITS.metadata_bytes + b"}"
    streamed = await _upload(harness.client, files=_valid_parts(metadata=oversized_metadata))
    _assert_problem(declared, status=413, code="payload_too_large")
    streamed_body = _assert_problem(streamed, status=413, code="payload_too_large")
    assert streamed_body["limits"] == {"metadata_bytes": UPLOAD_LIMITS.metadata_bytes}
    assert harness.workflow.commands == []


async def test_stream_enforces_wire_limit_without_content_length(
    harness: RouteHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = "wire-limit"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n'
        "Content-Type: application/json\r\n\r\n{}\r\n"
        f'--{boundary}\r\nContent-Disposition: form-data; name="findings"\r\n'
        "Content-Type: application/json\r\n\r\n" + (" " * 2048) + f"\r\n--{boundary}--\r\n"
    ).encode()

    async def chunks():
        for offset in range(0, len(body), 128):
            yield body[offset : offset + 128]

    monkeypatch.setattr(local_ingest, "UPLOAD_LIMITS", UploadLimits(wire_bytes=1024))
    response = await harness.client.post(
        "/api/v1/ingest/local-scans",
        content=chunks(),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Idempotency-Key": IDEMPOTENCY_KEY,
        },
    )
    body_json = _assert_problem(response, status=413, code="payload_too_large")
    assert body_json["limits"] == {"wire_bytes": 1024}


async def test_enforces_optional_artifact_and_result_count_limits(
    harness: RouteHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(local_ingest._PART_LIMITS, "sarif", 10)
    artifact_response = await _upload(
        harness.client,
        files=_valid_parts() + [("sarif", ("assurance.sarif", b"[          ]", "application/sarif+json"))],
    )
    artifact_body = _assert_problem(artifact_response, status=413, code="payload_too_large")
    assert artifact_body["limits"] == {"sarif_bytes": 10}

    findings = json.loads((FIXTURES / "valid" / "findings.json").read_text())
    findings["scanners"] = findings["scanners"] * (UPLOAD_LIMITS.scanner_results + 1)
    count_response = await _upload(
        harness.client,
        files=_valid_parts(findings=json.dumps(findings).encode()),
    )
    _assert_problem(count_response, status=422, code="schema_validation_failed")


async def test_outer_auth_middleware_allows_ingest_dependency_to_decide() -> None:
    from app.config import load_settings
    from app.main import create_app

    settings = replace(
        load_settings(),
        github_app_access_enabled=True,
        local_ingest_enabled=True,
        github_app_client_id="client",
        github_app_client_secret="secret",
        token_encryption_key="encryption-key",
        session_secret="session-secret-at-least-32-bytes-long",
        public_base_url="https://scan.example.test",
    )
    app = create_app(settings)
    app.dependency_overrides[require_scan_token_principal] = _principal
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://scan.example.test",
    ) as client:
        response = await client.get(
            "/api/v1/ingest/whoami",
            headers={"Authorization": "Bearer dedicated-scan-token"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["account"] == "alice@example.test"
