"""Framework-free records and decisions for server-side browser sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SessionDecision(StrEnum):
    AUTHENTICATED = "authenticated"
    INVALID = "invalid"
    REVOKED = "revoked"
    IDLE_EXPIRED = "idle_expired"
    ABSOLUTE_EXPIRED = "absolute_expired"


@dataclass(frozen=True)
class BrowserSessionRecord:
    session_id: str
    user_id: int
    session_digest: bytes = field(repr=False)
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None
    rotated_from_id: str | None = None


@dataclass(frozen=True)
class IssuedBrowserSession:
    cookie_value: str = field(repr=False)
    record: BrowserSessionRecord


@dataclass(frozen=True)
class SessionAuthenticationResult:
    decision: SessionDecision
    user_id: int | None = None

    @property
    def authenticated(self) -> bool:
        return self.decision is SessionDecision.AUTHENTICATED


class SessionValidationError(ValueError):
    """An opaque cookie or stored session record is malformed."""
