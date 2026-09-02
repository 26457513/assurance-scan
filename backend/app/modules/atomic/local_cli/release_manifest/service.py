"""Strict validation for signed local-CLI release metadata."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .models import CLIReleaseManifest, ReleaseManifestError


CLI_IMAGE = "ghcr.io/26457513/assurance-scan-cli"
SIGNATURE_ISSUER = "https://token.actions.githubusercontent.com"
_IDENTITY_PREFIX = (
    "https://github.com/26457513/assurance-scan/"
    ".github/workflows/publish-cli-image.yml@refs/tags/"
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
_PLATFORMS = frozenset(("linux/amd64", "linux/arm64"))
_FIELDS = frozenset(
    (
        "schema_version",
        "wrapper_min_version",
        "cli_version",
        "image",
        "oci_index_digest",
        "supported_platforms",
        "signature_identity",
        "signature_issuer",
        "published_at",
        "expires_at",
    )
)


def validate_release_manifest(
    document: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> CLIReleaseManifest:
    """Return a typed manifest only when every trust field is canonical."""

    if set(document) != _FIELDS:
        raise ReleaseManifestError("release manifest fields are invalid")
    if document.get("schema_version") != 1:
        raise ReleaseManifestError("release manifest version is unsupported")
    wrapper_min = document.get("wrapper_min_version")
    if not isinstance(wrapper_min, int) or isinstance(wrapper_min, bool) or wrapper_min < 1:
        raise ReleaseManifestError("wrapper minimum version is invalid")
    cli_version = document.get("cli_version")
    if not isinstance(cli_version, str) or not _VERSION.fullmatch(cli_version):
        raise ReleaseManifestError("CLI version is invalid")
    if document.get("image") != CLI_IMAGE:
        raise ReleaseManifestError("CLI image identity is invalid")
    digest = document.get("oci_index_digest")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ReleaseManifestError("CLI index digest is invalid")
    platforms = document.get("supported_platforms")
    if (
        not isinstance(platforms, list)
        or any(not isinstance(item, str) for item in platforms)
        or frozenset(platforms) != _PLATFORMS
        or len(platforms) != len(_PLATFORMS)
    ):
        raise ReleaseManifestError("CLI release platforms are invalid")
    identity = document.get("signature_identity")
    expected_identity = _IDENTITY_PREFIX + cli_version
    if identity != expected_identity:
        raise ReleaseManifestError("CLI signature identity is invalid")
    if document.get("signature_issuer") != SIGNATURE_ISSUER:
        raise ReleaseManifestError("CLI signature issuer is invalid")
    published_at = _timestamp(document.get("published_at"), "published")
    expires_at = _timestamp(document.get("expires_at"), "expiry")
    if expires_at <= published_at or expires_at - published_at > timedelta(days=7):
        raise ReleaseManifestError("release manifest validity window is invalid")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ReleaseManifestError("current time must include a timezone")
    if current > expires_at:
        raise ReleaseManifestError("release manifest has expired")
    return CLIReleaseManifest(
        schema_version=1,
        wrapper_min_version=wrapper_min,
        cli_version=cli_version,
        image=CLI_IMAGE,
        oci_index_digest=digest,
        supported_platforms=tuple(platforms),
        signature_identity=identity,
        signature_issuer=SIGNATURE_ISSUER,
        published_at=published_at,
        expires_at=expires_at,
    )


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReleaseManifestError(f"release manifest {label} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReleaseManifestError(
            f"release manifest {label} timestamp is invalid"
        ) from exc
    if parsed.tzinfo != timezone.utc or parsed.microsecond:
        raise ReleaseManifestError(f"release manifest {label} timestamp is invalid")
    return parsed


__all__ = [
    "CLI_IMAGE",
    "SIGNATURE_ISSUER",
    "validate_release_manifest",
]
