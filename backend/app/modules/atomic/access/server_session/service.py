"""Pure issuance and validation rules for opaque server-side sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import uuid
from datetime import datetime, timedelta
from typing import Protocol

from .models import (
    BrowserSessionRecord,
    IssuedBrowserSession,
    SessionAuthenticationResult,
    SessionDecision,
    SessionValidationError,
)


SESSION_COOKIE_NAME = "as_session"
SESSION_COOKIE_PREFIX = "ass_v1_"
SESSION_SECRET_BYTES = 32
SESSION_IDLE_LIMIT = timedelta(hours=12)
SESSION_ABSOLUTE_LIMIT = timedelta(days=7)
_COOKIE_PATTERN = re.compile(r"^ass_v1_[A-Za-z0-9_-]{43}$")


class SessionRandomPort(Protocol):
    def random_bytes(self, size: int) -> bytes: ...


def issue_browser_session(
    *,
    user_id: int,
    now: datetime,
    random: SessionRandomPort,
    rotated_from_id: str | None = None,
) -> IssuedBrowserSession:
    """Mint a 256-bit opaque cookie and its digest-only persistence record."""
    current = _aware(now)
    secret = _random_bytes(random, SESSION_SECRET_BYTES)
    cookie = SESSION_COOKIE_PREFIX + _encode(secret)
    record = BrowserSessionRecord(
        session_id=_random_uuid(random),
        user_id=user_id,
        session_digest=digest_session_cookie(cookie),
        created_at=current,
        last_seen_at=current,
        idle_expires_at=current + SESSION_IDLE_LIMIT,
        absolute_expires_at=current + SESSION_ABSOLUTE_LIMIT,
        rotated_from_id=rotated_from_id,
    )
    return IssuedBrowserSession(cookie_value=cookie, record=record)


def digest_session_cookie(cookie_value: str) -> bytes:
    if not isinstance(cookie_value, str) or _COOKIE_PATTERN.fullmatch(cookie_value) is None:
        raise SessionValidationError("browser session cookie has an invalid format")
    return hashlib.sha256(cookie_value.encode("ascii")).digest()


def authenticate_browser_session(
    cookie_value: str,
    record: BrowserSessionRecord | None,
    *,
    now: datetime,
) -> SessionAuthenticationResult:
    """Validate cookie binding, revocation, idle expiry and absolute expiry."""
    current = _aware(now)
    try:
        supplied_digest = digest_session_cookie(cookie_value)
    except SessionValidationError:
        supplied_digest = bytes(hashlib.sha256().digest_size)
    expected_digest = record.session_digest if record is not None else bytes(32)
    matches = hmac.compare_digest(supplied_digest, expected_digest)
    if record is None or not matches:
        return SessionAuthenticationResult(SessionDecision.INVALID)
    if record.revoked_at is not None:
        return SessionAuthenticationResult(SessionDecision.REVOKED)
    if current >= _aware(record.absolute_expires_at):
        return SessionAuthenticationResult(SessionDecision.ABSOLUTE_EXPIRED)
    if current >= _aware(record.idle_expires_at):
        return SessionAuthenticationResult(SessionDecision.IDLE_EXPIRED)
    return SessionAuthenticationResult(SessionDecision.AUTHENTICATED, record.user_id)


def refreshed_idle_expiry(record: BrowserSessionRecord, *, now: datetime) -> datetime:
    """Extend activity without ever crossing the immutable absolute limit."""
    current = _aware(now)
    return min(current + SESSION_IDLE_LIMIT, _aware(record.absolute_expires_at))


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _random_bytes(random: SessionRandomPort, size: int) -> bytes:
    value = random.random_bytes(size)
    if not isinstance(value, bytes) or len(value) != size:
        raise RuntimeError(f"random port returned invalid {size}-byte value")
    return value


def _random_uuid(random: SessionRandomPort) -> str:
    value = bytearray(_random_bytes(random, 16))
    value[6] = (value[6] & 0x0F) | 0x40
    value[8] = (value[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(value)))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("browser-session timestamps must be timezone-aware")
    return value
