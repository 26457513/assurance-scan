"""Strict GitHub Actions OIDC workload authentication."""

from .models import GithubOidcClaims, GithubRepositoryTrust, OidcValidationError
from .ports import RsaSignatureVerifier
from .service import (
    authenticate_github_oidc,
    authorize_default_branch_push,
    github_oidc_audience,
)

__all__ = [
    "GithubOidcClaims",
    "GithubRepositoryTrust",
    "OidcValidationError",
    "RsaSignatureVerifier",
    "authenticate_github_oidc",
    "authorize_default_branch_push",
    "github_oidc_audience",
]
