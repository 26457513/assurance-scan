"""Version-one local-scan protocol constants.

These values are product/security decisions shared by transport adapters,
workflows, the CLI, and contract tests. They contain no framework behavior.
"""

from __future__ import annotations

from dataclasses import dataclass


SCHEMA_VERSION = 1
API_PREFIX = "/api/v1/ingest"
TOKEN_PREFIX = "asu_v1_"
TOKEN_SELECTOR_BYTES = 12
TOKEN_SECRET_BYTES = 32
TOKEN_DEFAULT_EXPIRY_DAYS = 90
TOKEN_ALLOWED_EXPIRY_DAYS = (30, 90, 180)
TOKEN_MAX_EXPIRY_DAYS = 365
TOKEN_ACTIVE_LIMIT = 5
TOKEN_CREATION_HOURLY_LIMIT = 5
TOKEN_SCOPE = "scans:upload"


@dataclass(frozen=True)
class UploadLimits:
    """Hard default ceilings; deployments may configure lower values."""

    wire_bytes: int = 32 * 1024 * 1024
    parsed_bytes: int = 64 * 1024 * 1024
    metadata_bytes: int = 64 * 1024
    findings_bytes: int = 10 * 1024 * 1024
    sarif_bytes: int = 16 * 1024 * 1024
    sbom_bytes: int = 16 * 1024 * 1024
    findings_count: int = 20_000
    scanner_results: int = 32
    json_depth: int = 20
    path_chars: int = 1_024
    message_chars: int = 8_192


@dataclass(frozen=True)
class UsageLimits:
    """Default abuse and retained-storage controls."""

    uploads_per_token_hour: int = 10
    uploads_per_user_day: int = 100
    inflight_per_token: int = 1
    inflight_per_user: int = 2
    inflight_per_instance: int = 4
    retained_bytes_per_user: int = 1024 * 1024 * 1024
    retained_bytes_per_instance: int = 5 * 1024 * 1024 * 1024
    accepted_bytes_per_user_day: int = 500 * 1024 * 1024


@dataclass(frozen=True)
class RetentionDays:
    """Server-side retention defaults."""

    raw_artifacts: int = 30
    normalized_history: int = 365
    token_audit_after_inactive: int = 400
    deletion_tombstone: int = 30


UPLOAD_LIMITS = UploadLimits()
USAGE_LIMITS = UsageLimits()
RETENTION_DAYS = RetentionDays()


__all__ = [
    "API_PREFIX",
    "RETENTION_DAYS",
    "SCHEMA_VERSION",
    "TOKEN_ACTIVE_LIMIT",
    "TOKEN_CREATION_HOURLY_LIMIT",
    "TOKEN_ALLOWED_EXPIRY_DAYS",
    "TOKEN_DEFAULT_EXPIRY_DAYS",
    "TOKEN_MAX_EXPIRY_DAYS",
    "TOKEN_PREFIX",
    "TOKEN_SCOPE",
    "TOKEN_SECRET_BYTES",
    "TOKEN_SELECTOR_BYTES",
    "UPLOAD_LIMITS",
    "USAGE_LIMITS",
    "RetentionDays",
    "UploadLimits",
    "UsageLimits",
]
