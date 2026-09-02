"""Framework-free records for GitHub Actions workload identity."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class GithubOidcClaims:
    subject: str
    repository_id: int
    repository_owner_id: int
    repository: str
    run_id: int
    run_number: int
    run_attempt: int
    sha: str
    ref: str
    event_name: str
    actor: str
    actor_id: int
    workflow_ref: str
    workflow_sha: str
    issued_at: dt.datetime
    not_before: dt.datetime
    expires_at: dt.datetime
    jti: str


@dataclass(frozen=True)
class GithubRepositoryTrust:
    """Current authoritative repository identity used to authorize one upload."""

    repository_id: int
    owner_id: int
    full_name: str
    default_branch: str


class OidcValidationError(ValueError):
    """OIDC authentication or signed workload policy failed closed."""

    def __init__(self, code: str = "oidc_invalid") -> None:
        super().__init__(code)
        self.code = code


__all__ = ["GithubOidcClaims", "GithubRepositoryTrust", "OidcValidationError"]
