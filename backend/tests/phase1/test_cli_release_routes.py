"""HTTP distribution tests for signed CLI release metadata and the wrapper."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.cli_releases import router
from app.modules.shared.paths import RESOURCES_ROOT


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _manifest() -> dict[str, object]:
    published = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": 1,
        "wrapper_min_version": 1,
        "cli_version": "v1.2.3",
        "image": "ghcr.io/26457513/assurance-scan-cli",
        "oci_index_digest": "sha256:" + "a" * 64,
        "supported_platforms": ["linux/amd64", "linux/arm64"],
        "signature_identity": (
            "https://github.com/26457513/assurance-scan/"
            ".github/workflows/publish-cli-image.yml@refs/tags/v1.2.3"
        ),
        "signature_issuer": "https://token.actions.githubusercontent.com",
        "published_at": published.isoformat().replace("+00:00", "Z"),
        "expires_at": (published + timedelta(days=7)).isoformat().replace(
            "+00:00", "Z"
        ),
    }


@pytest.mark.anyio
async def test_serves_exact_validated_release_bytes_and_bundle(tmp_path) -> None:
    manifest_path = tmp_path / "release.json"
    bundle_path = tmp_path / "release.sigstore.json"
    manifest_path.write_text(json.dumps(_manifest()))
    bundle_path.write_text('{"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json"}')
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        cli_release_manifest_path=str(manifest_path),
        cli_release_bundle_path=str(bundle_path),
    )
    app.include_router(router, prefix="/api")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://scan.example.test"
    ) as client:
        manifest = await client.get("/api/v2/cli/releases/latest")
        bundle = await client.get("/api/v2/cli/releases/latest.sigstore.json")

    assert manifest.status_code == 200
    assert manifest.json()["cli_version"] == "v1.2.3"
    assert manifest.headers["x-content-type-options"] == "nosniff"
    assert bundle.status_code == 200
    assert bundle.json()["mediaType"].endswith("+json")


@pytest.mark.anyio
async def test_fails_closed_when_release_metadata_is_missing() -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        cli_release_manifest_path="",
        cli_release_bundle_path="",
    )
    app.include_router(router, prefix="/api")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://scan.example.test"
    ) as client:
        response = await client.get("/api/v2/cli/releases/latest")

    assert response.status_code == 503


@pytest.mark.anyio
async def test_wrapper_and_displayed_checksum_match() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://scan.example.test"
    ) as client:
        wrapper = await client.get("/api/v2/cli/releases/wrapper")
        checksum = await client.get("/api/v2/cli/releases/wrapper.sha256")

    expected = hashlib.sha256(
        (RESOURCES_ROOT / "bootstrap" / "assurance-scan").read_bytes()
    ).hexdigest()
    assert wrapper.status_code == 200
    assert wrapper.content.startswith(b"#!/bin/sh\n")
    assert checksum.text.strip() == expected
