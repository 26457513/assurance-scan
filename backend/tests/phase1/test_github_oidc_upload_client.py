"""Security and protocol tests for the single-attempt GitHub OIDC uploader."""
from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.infrastructure.github_oidc_upload import StdlibGithubOidcUploadTransport
from app.modules.atomic.ingestion.github_oidc_upload_client import (
    GithubUploadConfig,
    GithubUploadError,
    GithubUploadResponse,
    load_bundle,
    read_oidc_jwt,
    upload_once,
)


_JWT = "header.payload.signature"


class RecordingTransport:
    def __init__(self, status: int, body: bytes = b"{}") -> None:
        self.response = GithubUploadResponse(status, {}, body)
        self.calls: list[tuple[str, object, object]] = []

    def post(self, endpoint, bundle, config):
        self.calls.append((endpoint, bundle, config))
        return self.response


@pytest.fixture
def bundle_root(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    root.mkdir()
    metadata = {
        "producer": {
            "kind": "github-actions",
            "repository_id": 101,
            "run_id": 303,
            "run_attempt": 2,
        }
    }
    (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (root / "findings.json").write_text("{}", encoding="utf-8")
    (root / "source-contexts.json").write_text("{}", encoding="utf-8")
    (root / "results.sarif").write_text("{}", encoding="utf-8")
    (root / "envelope.sha256").write_text("a" * 64 + "\n", encoding="ascii")
    return root


@pytest.mark.parametrize(
    "payload",
    (
        b"",
        b"header.payload.signature\n",
        b"header.payload.signature trailing",
        b"header.payload.\xff",
        b"header.payload.sig\x00nature",
        b"x" * (16 * 1024 + 1),
    ),
)
def test_jwt_stdin_rejects_empty_trailing_or_unbounded_input(payload: bytes) -> None:
    with pytest.raises(GithubUploadError, match="invalid_oidc_input"):
        read_oidc_jwt(io.BytesIO(payload))


def test_jwt_is_secret_in_config_repr() -> None:
    token = read_oidc_jwt(io.BytesIO(_JWT.encode("ascii")))
    config = GithubUploadConfig("https://scan.example.test", token)

    assert token not in repr(config)


def test_bundle_derives_idempotency_and_allowlisted_parts(bundle_root: Path) -> None:
    bundle = load_bundle(bundle_root)

    assert bundle.idempotency_key == "101:303:2"
    assert bundle.payload_hash == "a" * 64
    assert tuple(bundle.parts) == ("metadata", "findings", "source_contexts", "sarif")


def test_bundle_rejects_symlinked_required_file(bundle_root: Path) -> None:
    target = bundle_root / "findings.json"
    target.unlink()
    target.symlink_to(bundle_root / "metadata.json")

    with pytest.raises(GithubUploadError, match="invalid_bundle"):
        load_bundle(bundle_root)


@pytest.mark.parametrize(
    ("status", "expected_retryable"),
    ((201, False), (408, True), (429, True), (503, True), (401, False), (409, False), (422, False), (507, False)),
)
def test_single_attempt_classifies_only_frozen_retry_statuses(
    bundle_root: Path,
    status: int,
    expected_retryable: bool,
) -> None:
    bundle = load_bundle(bundle_root)
    transport = RecordingTransport(status, b'{"code":"quota_exceeded"}')
    config = GithubUploadConfig("https://scan.example.test", _JWT)

    result = upload_once(bundle, config, transport=transport)

    assert result.retryable is expected_retryable
    assert len(transport.calls) == 1
    assert transport.calls[0][0] == "https://scan.example.test/api/v2/ingest/github-actions"


def test_uploader_container_is_minimal_nonroot_and_has_no_docker_cli() -> None:
    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile.ci-upload"
    content = dockerfile.read_text(encoding="utf-8")

    assert "FROM python:3.12-slim@sha256:" in content
    assert "USER 65532:65532" in content
    assert "Dockerfile.ci" not in content
    assert "docker:27-cli" not in content
    assert "local_cli" not in content


def test_stdlib_transport_streams_exact_parts_and_headers(bundle_root: Path) -> None:
    captured: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            captured["path"] = self.path
            captured["authorization"] = self.headers["Authorization"]
            captured["idempotency"] = self.headers["Idempotency-Key"]
            captured["payload_hash"] = self.headers["X-Assurance-Payload-SHA256"]
            captured["body"] = self.rfile.read(length)
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        bundle = load_bundle(bundle_root)
        result = upload_once(
            bundle,
            GithubUploadConfig(
                f"http://127.0.0.1:{server.server_port}",
                _JWT,
                allow_loopback_http=True,
            ),
            transport=StdlibGithubOidcUploadTransport(),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert result.status == 201
    assert captured["path"] == "/api/v2/ingest/github-actions"
    assert captured["authorization"] == f"Bearer {_JWT}"
    assert captured["idempotency"] == "101:303:2"
    assert captured["payload_hash"] == "a" * 64
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b'name="metadata"' in body
    assert b'name="findings"' in body
    assert b'name="source_contexts"' in body
    assert b'name="sarif"' in body
    assert b"application/json; charset=utf-8" in body
    assert b"application/sarif+json" in body
