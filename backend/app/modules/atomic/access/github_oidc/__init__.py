"""Strict GitHub Actions OIDC workload authentication."""

from .models import GithubOidcClaims, GithubRepositoryTrust, OidcValidationError
from .ports import GithubOidcReplayRepository, RsaSignatureVerifier
from .service import (
    authenticate_github_oidc,
    authorize_default_branch_push,
    consume_github_oidc_jti,
    github_oidc_audience,
    github_oidc_key_id,
    validate_github_payload_metadata,
)

__all__ = [
    "GithubOidcClaims",
    "GithubRepositoryTrust",
    "GithubOidcReplayRepository",
    "OidcValidationError",
    "RsaSignatureVerifier",
    "authenticate_github_oidc",
    "authorize_default_branch_push",
    "consume_github_oidc_jti",
    "github_oidc_audience",
    "github_oidc_key_id",
    "validate_github_payload_metadata",
]
