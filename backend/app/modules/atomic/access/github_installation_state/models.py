"""Framework-free state records for GitHub App installation setup."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class GithubInstallationStateMaterial:
    state_id: str
    state: str = field(repr=False)
    state_digest: bytes = field(repr=False)
    browser_session_id: str
    return_path: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ConsumedGithubInstallationState:
    return_path: str


class GithubInstallationStateValidationError(ValueError):
    """Installation setup state did not satisfy the fixed security contract."""
