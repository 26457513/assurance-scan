"""Contracts for the independently signed local-CLI release manifest."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CLIReleaseManifest:
    """Validated trust metadata consumed by the host wrapper."""

    schema_version: int
    wrapper_min_version: int
    cli_version: str
    image: str
    oci_index_digest: str
    supported_platforms: tuple[str, ...]
    signature_identity: str
    signature_issuer: str
    published_at: datetime
    expires_at: datetime


class ReleaseManifestError(ValueError):
    """The published release metadata is malformed or outside policy."""


__all__ = ["CLIReleaseManifest", "ReleaseManifestError"]
