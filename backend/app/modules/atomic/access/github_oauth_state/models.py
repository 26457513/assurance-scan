"""Framework-free GitHub OAuth state and PKCE contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class GithubOauthFlow(StrEnum):
    SIGNIN = "signin"
    LINK = "link"


@dataclass(frozen=True)
class GithubOauthStateMaterial:
    state_id: str
    state: str = field(repr=False)
    state_digest: bytes = field(repr=False)
    pkce_verifier: str = field(repr=False)
    pkce_challenge: str
    browser_session_id: str
    flow_kind: GithubOauthFlow
    return_path: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ConsumedGithubOauthState:
    """Minimum callback material released by successful one-time consumption."""

    pkce_verifier: str = field(repr=False)
    flow_kind: GithubOauthFlow
    return_path: str


class GithubOauthStateValidationError(ValueError):
    """OAuth state input did not satisfy the fixed security contract."""
