"""Frozen protocol vocabulary and ceilings for v2 push ingestion."""

from __future__ import annotations

from dataclasses import dataclass


SCHEMA_VERSION = 2
ENVELOPE_DOMAIN = b"assurance-scan-envelope-v2"
ENVELOPE_PARTS = ("metadata", "findings", "source_contexts", "sarif", "sbom")
REQUIRED_PARTS = frozenset(("metadata", "findings", "source_contexts"))
OPTIONAL_PARTS = frozenset(("sarif", "sbom"))
PART_MEDIA_TYPES = {
    "metadata": ("application/json; charset=utf-8",),
    "findings": ("application/json; charset=utf-8",),
    "source_contexts": ("application/json; charset=utf-8",),
    "sarif": ("application/sarif+json", "application/json"),
    "sbom": ("application/vnd.cyclonedx+json", "application/json"),
}
SCANNER_KINDS = (
    "semgrep",
    "gitleaks",
    "trivy-fs",
    "trivy-config",
    "trivy-image",
    "syft",
    "grype",
    "osv-scanner",
    "tribal",
)
SCANNER_STATUSES = ("completed", "failed", "skipped")
SCANNER_ERROR_CODES = (
    "scanner_dependency_failed",
    "scanner_exit_nonzero",
    "scanner_not_configured",
    "scanner_output_invalid",
    "scanner_timeout",
    "scanner_unsupported",
)
INGEST_ATTEMPT_OUTCOMES = ("accepted", "replayed", "rejected", "failed_internal")
INGEST_REASON_CODES = (
    "accepted",
    "artifact_mismatch",
    "authentication_rate_limited",
    "capacity_exceeded",
    "duplicate_json_key",
    "duplicate_part",
    "github_verification_failed",
    "idempotency_conflict",
    "idempotent_replay",
    "insufficient_scope",
    "internal_persistence_failed",
    "invalid_content_type",
    "invalid_credential",
    "invalid_json",
    "invalid_part_media_type",
    "malformed_multipart",
    "non_default_branch",
    "oidc_invalid",
    "oidc_replayed",
    "project_not_enabled",
    "quota_exceeded",
    "repository_not_authorized",
    "schema_validation_failed",
    "stale_entitlement",
    "storage_quota_exceeded",
    "unexpected_part",
    "unsupported_content_encoding",
    "unsupported_event",
    "wire_limit_exceeded",
)
PROBLEM_CODES = tuple(
    code for code in INGEST_REASON_CODES if code not in {"accepted", "idempotent_replay"}
)
OIDC_REQUIRED_CLAIMS = (
    "iss",
    "aud",
    "sub",
    "repository_id",
    "repository_owner_id",
    "repository",
    "run_id",
    "run_number",
    "run_attempt",
    "sha",
    "ref",
    "event_name",
    "actor",
    "actor_id",
    "workflow_ref",
    "workflow_sha",
    "iat",
    "nbf",
    "exp",
    "jti",
)
WEBHOOK_EVENT_ACTIONS = (
    ("installation", "created"),
    ("installation", "deleted"),
    ("installation", "suspend"),
    ("installation", "unsuspend"),
    ("installation", "new_permissions_accepted"),
    ("installation_repositories", "added"),
    ("installation_repositories", "removed"),
    ("repository", "edited"),
    ("repository", "renamed"),
    ("repository", "transferred"),
    ("repository", "archived"),
    ("repository", "unarchived"),
    ("repository", "deleted"),
    ("installation_target", "renamed"),
)


@dataclass(frozen=True)
class OIDCPolicyV2:
    issuer: str = "https://token.actions.githubusercontent.com"
    discovery_url: str = (
        "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
    )
    jwks_url: str = "https://token.actions.githubusercontent.com/.well-known/jwks"
    audience_path: str = "/api/v2/ingest/github-actions"
    algorithm: str = "RS256"
    token_type: str = "JWT"
    maximum_jwt_bytes: int = 16 * 1024
    maximum_kid_bytes: int = 128
    jwks_cache_seconds: int = 60 * 60
    clock_skew_seconds: int = 60
    maximum_lifetime_seconds: int = 10 * 60
    consumed_jti_extra_retention_seconds: int = 5 * 60


@dataclass(frozen=True)
class WebhookPolicyV2:
    maximum_body_bytes: int = 2 * 1024 * 1024
    delivery_retention_days: int = 30
    secret_overlap_seconds: int = 60 * 60
    signature_algorithm: str = "sha256"


@dataclass(frozen=True)
class SourceContextLimitsV2:
    unique_windows: int = 500
    lines_per_window: int = 11
    bytes_per_line: int = 1024
    bytes_per_window: int = 8192
    decoded_bytes_per_request: int = 2 * 1024 * 1024


@dataclass(frozen=True)
class ProblemPolicyV2:
    code: str
    status: int
    retryable: bool
    retry_after: bool = False


PROBLEM_POLICIES_V2 = (
    ProblemPolicyV2("artifact_mismatch", 422, False),
    ProblemPolicyV2("authentication_rate_limited", 429, True, True),
    ProblemPolicyV2("capacity_exceeded", 429, True, True),
    ProblemPolicyV2("duplicate_json_key", 400, False),
    ProblemPolicyV2("duplicate_part", 400, False),
    ProblemPolicyV2("github_verification_failed", 503, True, True),
    ProblemPolicyV2("idempotency_conflict", 409, False),
    ProblemPolicyV2("insufficient_scope", 403, False),
    ProblemPolicyV2("internal_persistence_failed", 500, True, True),
    ProblemPolicyV2("invalid_content_type", 415, False),
    ProblemPolicyV2("invalid_credential", 401, False),
    ProblemPolicyV2("invalid_json", 400, False),
    ProblemPolicyV2("invalid_part_media_type", 415, False),
    ProblemPolicyV2("malformed_multipart", 400, False),
    ProblemPolicyV2("non_default_branch", 403, False),
    ProblemPolicyV2("oidc_invalid", 401, False),
    ProblemPolicyV2("oidc_replayed", 401, False),
    ProblemPolicyV2("project_not_enabled", 403, False),
    ProblemPolicyV2("quota_exceeded", 429, True, True),
    ProblemPolicyV2("repository_not_authorized", 403, False),
    ProblemPolicyV2("schema_validation_failed", 422, False),
    ProblemPolicyV2("stale_entitlement", 403, False),
    ProblemPolicyV2("storage_quota_exceeded", 507, False),
    ProblemPolicyV2("unexpected_part", 400, False),
    ProblemPolicyV2("unsupported_content_encoding", 415, False),
    ProblemPolicyV2("unsupported_event", 422, False),
    ProblemPolicyV2("wire_limit_exceeded", 413, False),
)


@dataclass(frozen=True)
class EnvelopeLimitsV2:
    wire_bytes: int = 32 * 1024 * 1024
    parsed_bytes: int = 64 * 1024 * 1024
    metadata_bytes: int = 64 * 1024
    findings_bytes: int = 10 * 1024 * 1024
    source_contexts_bytes: int = 10 * 1024 * 1024
    sarif_bytes: int = 16 * 1024 * 1024
    sbom_bytes: int = 16 * 1024 * 1024
    findings_count: int = 20_000
    scanner_results: int = 32
    json_depth: int = 20
    path_chars: int = 1_024
    message_chars: int = 8_192


@dataclass(frozen=True)
class GitHubUsageLimitsV2:
    uploads_per_repository_hour: int = 30
    uploads_per_owner_day: int = 500
    inflight_per_repository: int = 2
    accepted_bytes_per_owner_day: int = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class SharedUsageLimitsV2:
    inflight_per_instance: int = 8
    inflight_local_per_instance: int = 4


@dataclass(frozen=True)
class LocalUsageLimitsV2:
    uploads_per_token_hour: int = 10
    uploads_per_user_day: int = 100
    inflight_per_token: int = 1
    inflight_per_user: int = 2
    accepted_bytes_per_user_day: int = 500 * 1024 * 1024
    retained_bytes_per_user: int = 1024 * 1024 * 1024
    retained_bytes_per_instance: int = 5 * 1024 * 1024 * 1024
    authentication_failures_per_ip_ten_minutes: int = 20
    authentication_failures_per_selector_ten_minutes: int = 10


ENVELOPE_LIMITS_V2 = EnvelopeLimitsV2()
GITHUB_USAGE_LIMITS_V2 = GitHubUsageLimitsV2()
SHARED_USAGE_LIMITS_V2 = SharedUsageLimitsV2()
LOCAL_USAGE_LIMITS_V2 = LocalUsageLimitsV2()
OIDC_POLICY_V2 = OIDCPolicyV2()
WEBHOOK_POLICY_V2 = WebhookPolicyV2()
SOURCE_CONTEXT_LIMITS_V2 = SourceContextLimitsV2()


__all__ = [
    "ENVELOPE_DOMAIN",
    "ENVELOPE_LIMITS_V2",
    "ENVELOPE_PARTS",
    "GITHUB_USAGE_LIMITS_V2",
    "INGEST_ATTEMPT_OUTCOMES",
    "INGEST_REASON_CODES",
    "LOCAL_USAGE_LIMITS_V2",
    "LocalUsageLimitsV2",
    "OIDC_POLICY_V2",
    "OIDCPolicyV2",
    "OIDC_REQUIRED_CLAIMS",
    "OPTIONAL_PARTS",
    "PART_MEDIA_TYPES",
    "PROBLEM_CODES",
    "PROBLEM_POLICIES_V2",
    "ProblemPolicyV2",
    "REQUIRED_PARTS",
    "SCANNER_ERROR_CODES",
    "SCANNER_KINDS",
    "SCANNER_STATUSES",
    "SCHEMA_VERSION",
    "SHARED_USAGE_LIMITS_V2",
    "SOURCE_CONTEXT_LIMITS_V2",
    "SourceContextLimitsV2",
    "EnvelopeLimitsV2",
    "GitHubUsageLimitsV2",
    "SharedUsageLimitsV2",
    "WEBHOOK_EVENT_ACTIONS",
    "WEBHOOK_POLICY_V2",
    "WebhookPolicyV2",
]
