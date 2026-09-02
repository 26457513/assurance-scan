"""Strict signed release-manifest validation tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.modules.atomic.local_cli.release_manifest import (
    ReleaseManifestError,
    validate_release_manifest,
)


NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def _manifest() -> dict[str, object]:
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
        "published_at": "2026-09-01T12:00:00Z",
        "expires_at": "2026-09-08T12:00:00Z",
    }


def test_accepts_exact_supported_release_contract() -> None:
    result = validate_release_manifest(_manifest(), now=NOW)

    assert result.cli_version == "v1.2.3"
    assert result.oci_index_digest == "sha256:" + "a" * 64
    assert result.supported_platforms == ("linux/amd64", "linux/arm64")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("image", "ghcr.io/example/forged"),
        ("oci_index_digest", "sha256:short"),
        ("supported_platforms", ["linux/amd64"]),
        ("signature_identity", "https://github.com/example/forged"),
        ("signature_issuer", "https://issuer.example"),
        ("expires_at", "2026-09-09T12:00:00Z"),
    ),
)
def test_rejects_changed_trust_fields(field: str, value: object) -> None:
    document = _manifest()
    document[field] = value

    with pytest.raises(ReleaseManifestError):
        validate_release_manifest(document, now=NOW)


def test_rejects_expired_or_extended_manifest() -> None:
    expired = _manifest()
    expired["expires_at"] = "2026-09-02T11:59:59Z"
    with pytest.raises(ReleaseManifestError, match="expired"):
        validate_release_manifest(expired, now=NOW)

    extended = _manifest()
    extended["expires_at"] = "2026-09-08T12:00:01Z"
    with pytest.raises(ReleaseManifestError, match="validity"):
        validate_release_manifest(extended, now=NOW)


def test_rejects_unknown_fields() -> None:
    document = _manifest()
    document["redirect"] = "https://attacker.example"

    with pytest.raises(ReleaseManifestError, match="fields"):
        validate_release_manifest(document, now=NOW)
