"""Negative tests for local Docker and sibling-mount trust decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.atomic.local_cli.runtime_trust import (
    RuntimeTrustError,
    parse_local_docker_endpoint,
    sibling_snapshot_path,
)


REQUEST_ID = "018f47a2-4c72-4c9e-9f60-780cb70b8fe4"


@pytest.mark.parametrize(
    ("endpoint", "rootless"),
    (
        ("unix:///var/run/docker.sock", False),
        ("unix:///Users/alice/.docker/run/docker.sock", False),
        ("unix:///run/user/1000/docker.sock", True),
    ),
)
def test_accepts_local_macos_and_linux_unix_sockets(
    endpoint: str, rootless: bool
) -> None:
    result = parse_local_docker_endpoint(endpoint)

    assert result.socket_path.is_absolute()
    assert result.rootless is rootless


@pytest.mark.parametrize(
    "endpoint",
    (
        "tcp://127.0.0.1:2375",
        "ssh://builder@example.test",
        "npipe:////./pipe/docker_engine",
        "unix://remote/var/run/docker.sock",
        "unix:///var/run/../run/docker.sock",
        "unix:///var//run/docker.sock",
        "unix:///var/run/%64ocker.sock",
        "unix:///%00docker.sock",
    ),
)
def test_rejects_remote_or_noncanonical_docker_endpoints(endpoint: str) -> None:
    with pytest.raises(RuntimeTrustError):
        parse_local_docker_endpoint(endpoint)


def test_maps_only_the_matching_request_source_directory() -> None:
    root = f"/Users/alice/.cache/assurance-scan/runs/{REQUEST_ID}"

    assert sibling_snapshot_path(root, REQUEST_ID) == Path(root) / "source"


@pytest.mark.parametrize(
    "root",
    (
        f"relative/runs/{REQUEST_ID}",
        f"/tmp/not-runs/{REQUEST_ID}",
        f"/tmp/runs/../runs/{REQUEST_ID}",
        f"/tmp/runs//{REQUEST_ID}",
        "/tmp/runs/9d729629-2af3-4498-8342-7ed237f44a6f",
    ),
)
def test_rejects_untrusted_sibling_host_paths(root: str) -> None:
    with pytest.raises(RuntimeTrustError):
        sibling_snapshot_path(root, REQUEST_ID)


def test_wrapper_contract_uses_digest_only_cli_and_bounded_mounts() -> None:
    wrapper = (
        Path(__file__).resolve().parents[3] / "resources" / "bootstrap" / "assurance-scan"
    ).read_text()

    assert "VERIFIER_IMAGE=ghcr.io/sigstore/cosign/cosign@sha256:" in wrapper
    assert "--pull=never" in wrapper
    assert 'CLI_IMAGE=$IMAGE@$digest' in wrapper
    assert 'ASSURANCE_SCAN_HOST_RUN_CACHE="$run_cache"' in wrapper
    assert '"$PROJECT_ROOT:/workspace:ro"' in wrapper
    assert '"$CONFIG_ROOT:/config:ro"' in wrapper
    assert "ssh://" not in wrapper
    assert "$IMAGE:stable" not in wrapper
