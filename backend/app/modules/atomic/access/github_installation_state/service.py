"""Pure issuance and digest rules for installation setup state."""

from __future__ import annotations

import base64
import hashlib
import re
import uuid
from datetime import datetime, timedelta
from typing import Protocol

from .models import GithubInstallationStateMaterial, GithubInstallationStateValidationError


INSTALLATION_STATE_TTL = timedelta(minutes=10)
INSTALLATION_STATE_BYTES = 32
ALLOWED_INSTALLATION_RETURN_PATHS = frozenset({"/", "/projects", "/setup"})
_STATE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


class GithubInstallationRandomPort(Protocol):
    def random_bytes(self, size: int) -> bytes: ...


def issue_github_installation_state(
    *,
    browser_session_id: str,
    return_path: str,
    now: datetime,
    random: GithubInstallationRandomPort,
) -> GithubInstallationStateMaterial:
    """Issue independent 256-bit setup state bound to one browser session."""
    if return_path not in ALLOWED_INSTALLATION_RETURN_PATHS:
        raise GithubInstallationStateValidationError("installation return path is not allowlisted")
    if not browser_session_id:
        raise GithubInstallationStateValidationError("browser session id is required")
    current = _aware(now)
    state = _encode(_random_bytes(random, INSTALLATION_STATE_BYTES))
    return GithubInstallationStateMaterial(
        state_id=_random_uuid(random),
        state=state,
        state_digest=digest_installation_state(state),
        browser_session_id=browser_session_id,
        return_path=return_path,
        created_at=current,
        expires_at=current + INSTALLATION_STATE_TTL,
    )


def digest_installation_state(state: str) -> bytes:
    if not isinstance(state, str) or _STATE_PATTERN.fullmatch(state) is None:
        raise GithubInstallationStateValidationError("installation state has an invalid format")
    return hashlib.sha256(state.encode("ascii")).digest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _random_bytes(random: GithubInstallationRandomPort, size: int) -> bytes:
    value = random.random_bytes(size)
    if not isinstance(value, bytes) or len(value) != size:
        raise RuntimeError(f"random port returned invalid {size}-byte value")
    return value


def _random_uuid(random: GithubInstallationRandomPort) -> str:
    value = bytearray(_random_bytes(random, 16))
    value[6] = (value[6] & 0x0F) | 0x40
    value[8] = (value[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(value)))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("installation-state timestamps must be timezone-aware")
    return value
