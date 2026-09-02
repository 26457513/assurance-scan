"""Framework-free records for a GitHub pre-authentication transaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class GithubSigninMaterial:
    transaction_id: str
    transaction_cookie: str = field(repr=False)
    transaction_digest: bytes = field(repr=False)
    state: str = field(repr=False)
    state_digest: bytes = field(repr=False)
    pkce_verifier: str = field(repr=False)
    pkce_challenge: str
    return_path: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ConsumedGithubSignin:
    pkce_verifier: str = field(repr=False)
    return_path: str
