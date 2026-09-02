"""Pure OAuth state, PKCE S256 and redirect allowlist operations."""

from __future__ import annotations

import base64
import hashlib
import re
import uuid
from datetime import datetime, timedelta
from typing import Protocol

from .models import GithubOauthFlow, GithubOauthStateMaterial, GithubOauthStateValidationError


OAUTH_STATE_TTL = timedelta(minutes=10)
OAUTH_STATE_BYTES = 32
PKCE_VERIFIER_BYTES = 64
ALLOWED_RETURN_PATHS = frozenset({"/", "/projects", "/setup"})
_STATE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


class GithubOauthRandomPort(Protocol):
    def random_bytes(self, size: int) -> bytes: ...


def issue_github_oauth_state(
    *,
    browser_session_id: str,
    flow_kind: GithubOauthFlow,
    return_path: str,
    now: datetime,
    random: GithubOauthRandomPort,
) -> GithubOauthStateMaterial:
    """Create independent 256-bit state and a high-entropy PKCE S256 pair."""
    if return_path not in ALLOWED_RETURN_PATHS:
        raise GithubOauthStateValidationError("OAuth return path is not allowlisted")
    current = _aware(now)
    state = _encode(_random_bytes(random, OAUTH_STATE_BYTES))
    verifier = _encode(_random_bytes(random, PKCE_VERIFIER_BYTES))
    challenge = _encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return GithubOauthStateMaterial(
        state_id=_random_uuid(random),
        state=state,
        state_digest=digest_oauth_state(state),
        pkce_verifier=verifier,
        pkce_challenge=challenge,
        browser_session_id=browser_session_id,
        flow_kind=flow_kind,
        return_path=return_path,
        created_at=current,
        expires_at=current + OAUTH_STATE_TTL,
    )


def digest_oauth_state(state: str) -> bytes:
    if not isinstance(state, str) or _STATE_PATTERN.fullmatch(state) is None:
        raise GithubOauthStateValidationError("OAuth state has an invalid format")
    return hashlib.sha256(state.encode("ascii")).digest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _random_bytes(random: GithubOauthRandomPort, size: int) -> bytes:
    value = random.random_bytes(size)
    if not isinstance(value, bytes) or len(value) != size:
        raise RuntimeError(f"random port returned invalid {size}-byte value")
    return value


def _random_uuid(random: GithubOauthRandomPort) -> str:
    value = bytearray(_random_bytes(random, 16))
    value[6] = (value[6] & 0x0F) | 0x40
    value[8] = (value[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(value)))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("OAuth-state timestamps must be timezone-aware")
    return value
