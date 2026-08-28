"""Framework-free contracts for version-one scan-upload tokens."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ScanTokenDecision(StrEnum):
    """Internal authentication decision; transports map these to generic errors."""

    AUTHENTICATED = "authenticated"
    INVALID = "invalid"
    USER_DISABLED = "user_disabled"
    REVOKED = "revoked"
    EXPIRED = "expired"
    INSUFFICIENT_SCOPE = "insufficient_scope"


class ScanTokenCreateStorageDecision(StrEnum):
    """Atomic outcomes returned by a transactional persistence adapter."""

    CREATED = "created"
    ACTIVE_LIMIT_REACHED = "active_limit_reached"
    CREATION_RATE_LIMITED = "creation_rate_limited"
    LABEL_CONFLICT = "label_conflict"
    SELECTOR_COLLISION = "selector_collision"


@dataclass(frozen=True)
class CreateScanTokenCommand:
    """Inputs accepted by the token-issuance capability."""

    user_id: int
    label: str
    expiry_days: int | None = None


@dataclass(frozen=True)
class ParsedScanToken:
    """Canonical selector and decoded secret from a bearer token."""

    selector: str
    secret: bytes = field(repr=False)


@dataclass(frozen=True)
class ScanTokenRecord:
    """Persistence-neutral token row created or loaded by an adapter."""

    token_id: str
    user_id: int
    label: str
    label_key: str
    selector: str
    secret_digest: bytes = field(repr=False)
    scope: str
    token_version: int
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class ScanTokenAuthenticationRecord:
    """Token row joined to the minimum user state needed for authentication."""

    token: ScanTokenRecord
    user_email: str
    user_disabled_at: datetime | None = None


@dataclass(frozen=True)
class IssuedScanToken:
    """One-time plaintext token plus the safely persisted record."""

    plaintext_token: str = field(repr=False)
    record: ScanTokenRecord


@dataclass(frozen=True)
class ScanTokenPrincipal:
    """Authenticated identity supplied to application workflows."""

    token_id: str
    user_id: int
    user_email: str
    token_label: str
    scope: str
    expires_at: datetime


@dataclass(frozen=True)
class ScanTokenAuthenticationResult:
    """Authentication decision and principal, when authentication succeeded."""

    decision: ScanTokenDecision
    principal: ScanTokenPrincipal | None = None

    @property
    def authenticated(self) -> bool:
        return self.decision is ScanTokenDecision.AUTHENTICATED


class ScanTokenError(ValueError):
    """Base class for expected token-capability failures."""


class ScanTokenValidationError(ScanTokenError):
    """A caller supplied an invalid label, expiry or token representation."""


class ScanTokenActiveLimitError(ScanTokenError):
    """The user already owns the maximum number of active tokens."""


class ScanTokenCreationRateLimitError(ScanTokenError):
    """The user created too many tokens in the current hour."""


class ScanTokenLabelConflictError(ScanTokenError):
    """The normalized label conflicts with another active token."""


class ScanTokenSelectorCollisionError(ScanTokenError):
    """Random token identity generation repeatedly collided in storage."""


__all__ = [
    "CreateScanTokenCommand",
    "IssuedScanToken",
    "ParsedScanToken",
    "ScanTokenActiveLimitError",
    "ScanTokenAuthenticationRecord",
    "ScanTokenAuthenticationResult",
    "ScanTokenCreateStorageDecision",
    "ScanTokenCreationRateLimitError",
    "ScanTokenDecision",
    "ScanTokenError",
    "ScanTokenLabelConflictError",
    "ScanTokenPrincipal",
    "ScanTokenRecord",
    "ScanTokenSelectorCollisionError",
    "ScanTokenValidationError",
]
