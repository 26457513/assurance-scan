"""Pure scan-token issuance, parsing and authentication decisions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import unicodedata
import uuid
from datetime import datetime, timedelta

from app.modules.shared.contracts.local_scan import (
    TOKEN_ACTIVE_LIMIT,
    TOKEN_CREATION_HOURLY_LIMIT,
    TOKEN_DEFAULT_EXPIRY_DAYS,
    TOKEN_MAX_EXPIRY_DAYS,
    TOKEN_PREFIX,
    TOKEN_SCOPE,
    TOKEN_SECRET_BYTES,
    TOKEN_SELECTOR_BYTES,
)

from .models import (
    CreateScanTokenCommand,
    IssuedScanToken,
    ParsedScanToken,
    ScanTokenActiveLimitError,
    ScanTokenAuthenticationResult,
    ScanTokenCreateStorageDecision,
    ScanTokenCreationRateLimitError,
    ScanTokenDecision,
    ScanTokenLabelConflictError,
    ScanTokenPrincipal,
    ScanTokenRecord,
    ScanTokenSelectorCollisionError,
    ScanTokenValidationError,
)
from .ports import ScanTokenClockPort, ScanTokenRandomPort, ScanTokenRepositoryPort


_SELECTOR_CHARS = 16
_SECRET_CHARS = 43
_TOKEN_PATTERN = re.compile(
    rf"^{re.escape(TOKEN_PREFIX)}([A-Za-z0-9_-]{{{_SELECTOR_CHARS}}})\."
    rf"([A-Za-z0-9_-]{{{_SECRET_CHARS}}})$"
)
_DUMMY_SECRET_DIGEST = hashlib.sha256(bytes(TOKEN_SECRET_BYTES)).digest()
_MAX_COLLISION_ATTEMPTS = 4


def normalize_scan_token_label(label: str) -> tuple[str, str]:
    """Return the NFKC display label and case-insensitive uniqueness key."""
    if not isinstance(label, str):
        raise ScanTokenValidationError("token label must be text")
    normalized = unicodedata.normalize("NFKC", label)
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ScanTokenValidationError("token label must not contain control characters")
    normalized = normalized.strip()
    if not 1 <= len(normalized) <= 64:
        raise ScanTokenValidationError("token label must contain 1 to 64 characters")
    return normalized, normalized.casefold()


def normalize_expiry_days(expiry_days: int | None) -> int:
    """Apply the default expiry and enforce the server's hard maximum."""
    if expiry_days is None:
        return TOKEN_DEFAULT_EXPIRY_DAYS
    if isinstance(expiry_days, bool) or not isinstance(expiry_days, int):
        raise ScanTokenValidationError("token expiry must be a whole number of days")
    if not 1 <= expiry_days <= TOKEN_MAX_EXPIRY_DAYS:
        raise ScanTokenValidationError(f"token expiry must be between 1 and {TOKEN_MAX_EXPIRY_DAYS} days")
    return expiry_days


def digest_token_secret(secret: bytes) -> bytes:
    """Return the only representation of a token secret that may be stored."""
    return hashlib.sha256(secret).digest()


def parse_scan_token(plaintext_token: str) -> ParsedScanToken:
    """Parse a canonical unpadded-base64url ``asu_v1`` bearer token."""
    if not isinstance(plaintext_token, str):
        raise ScanTokenValidationError("scan token must be text")
    match = _TOKEN_PATTERN.fullmatch(plaintext_token)
    if match is None:
        raise ScanTokenValidationError("scan token has an invalid format")
    selector, encoded_secret = match.groups()
    try:
        selector_bytes = _decode_unpadded_base64url(selector)
        secret = _decode_unpadded_base64url(encoded_secret)
    except ValueError as exc:
        raise ScanTokenValidationError("scan token has invalid base64url data") from exc
    if len(selector_bytes) != TOKEN_SELECTOR_BYTES or len(secret) != TOKEN_SECRET_BYTES:
        raise ScanTokenValidationError("scan token has invalid component lengths")
    if _encode_unpadded_base64url(selector_bytes) != selector:
        raise ScanTokenValidationError("scan token selector is not canonical")
    if _encode_unpadded_base64url(secret) != encoded_secret:
        raise ScanTokenValidationError("scan token secret is not canonical")
    return ParsedScanToken(selector=selector, secret=secret)


async def create_scan_token(
    command: CreateScanTokenCommand,
    *,
    repository: ScanTokenRepositoryPort,
    clock: ScanTokenClockPort,
    random: ScanTokenRandomPort,
) -> IssuedScanToken:
    """Issue and transactionally persist a new token with one-time plaintext."""
    label, label_key = normalize_scan_token_label(command.label)
    expiry_days = normalize_expiry_days(command.expiry_days)
    now = _aware_time(clock.now())

    for _attempt in range(_MAX_COLLISION_ATTEMPTS):
        selector_bytes = _random_bytes(random, TOKEN_SELECTOR_BYTES)
        secret = _random_bytes(random, TOKEN_SECRET_BYTES)
        token_id = _random_uuid(random)
        selector = _encode_unpadded_base64url(selector_bytes)
        encoded_secret = _encode_unpadded_base64url(secret)
        record = ScanTokenRecord(
            token_id=token_id,
            user_id=command.user_id,
            label=label,
            label_key=label_key,
            selector=selector,
            secret_digest=digest_token_secret(secret),
            scope=TOKEN_SCOPE,
            token_version=1,
            created_at=now,
            expires_at=now + timedelta(days=expiry_days),
        )
        decision = await repository.create_token(
            record,
            now=now,
            active_limit=TOKEN_ACTIVE_LIMIT,
            creation_hourly_limit=TOKEN_CREATION_HOURLY_LIMIT,
        )
        if decision is ScanTokenCreateStorageDecision.CREATED:
            return IssuedScanToken(
                plaintext_token=f"{TOKEN_PREFIX}{selector}.{encoded_secret}",
                record=record,
            )
        if decision is ScanTokenCreateStorageDecision.ACTIVE_LIMIT_REACHED:
            raise ScanTokenActiveLimitError("active scan-token limit reached")
        if decision is ScanTokenCreateStorageDecision.CREATION_RATE_LIMITED:
            raise ScanTokenCreationRateLimitError("scan-token creation rate limit reached")
        if decision is ScanTokenCreateStorageDecision.LABEL_CONFLICT:
            raise ScanTokenLabelConflictError("an active token already uses this label")
        if decision is not ScanTokenCreateStorageDecision.SELECTOR_COLLISION:
            raise RuntimeError(f"unsupported scan-token storage decision: {decision!r}")
    raise ScanTokenSelectorCollisionError("could not allocate a unique token selector")


async def authenticate_scan_token(
    plaintext_token: str,
    *,
    repository: ScanTokenRepositoryPort,
    clock: ScanTokenClockPort,
    required_scope: str = TOKEN_SCOPE,
) -> ScanTokenAuthenticationResult:
    """Authenticate a bearer token without leaking credential-state distinctions."""
    try:
        parsed = parse_scan_token(plaintext_token)
    except ScanTokenValidationError:
        _constant_time_secret_match(b"", _DUMMY_SECRET_DIGEST)
        return ScanTokenAuthenticationResult(ScanTokenDecision.INVALID)

    authentication_record = await repository.find_for_authentication(parsed.selector)
    expected_digest = (
        authentication_record.token.secret_digest
        if authentication_record is not None
        and len(authentication_record.token.secret_digest) == hashlib.sha256().digest_size
        else _DUMMY_SECRET_DIGEST
    )
    secret_matches = _constant_time_secret_match(parsed.secret, expected_digest)
    if authentication_record is None or not secret_matches:
        return ScanTokenAuthenticationResult(ScanTokenDecision.INVALID)

    token = authentication_record.token
    now = _aware_time(clock.now())
    if authentication_record.user_disabled_at is not None:
        return ScanTokenAuthenticationResult(ScanTokenDecision.USER_DISABLED)
    if token.revoked_at is not None:
        return ScanTokenAuthenticationResult(ScanTokenDecision.REVOKED)
    if _aware_time(token.expires_at) <= now:
        return ScanTokenAuthenticationResult(ScanTokenDecision.EXPIRED)
    if not hmac.compare_digest(token.scope.encode(), required_scope.encode()):
        return ScanTokenAuthenticationResult(ScanTokenDecision.INSUFFICIENT_SCOPE)

    return ScanTokenAuthenticationResult(
        ScanTokenDecision.AUTHENTICATED,
        ScanTokenPrincipal(
            token_id=token.token_id,
            user_id=token.user_id,
            account_name=authentication_record.account_name,
            token_label=token.label,
            scope=token.scope,
            expires_at=token.expires_at,
        ),
    )


def _constant_time_secret_match(secret: bytes, expected_digest: bytes) -> bool:
    return hmac.compare_digest(digest_token_secret(secret), expected_digest)


def _encode_unpadded_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_unpadded_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _random_bytes(random: ScanTokenRandomPort, size: int) -> bytes:
    value = random.random_bytes(size)
    if not isinstance(value, bytes) or len(value) != size:
        raise RuntimeError(f"random port returned invalid {size}-byte value")
    return value


def _random_uuid(random: ScanTokenRandomPort) -> str:
    value = bytearray(_random_bytes(random, 16))
    value[6] = (value[6] & 0x0F) | 0x40
    value[8] = (value[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(value)))


def _aware_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("scan-token clock and stored timestamps must be timezone-aware")
    return value


__all__ = [
    "authenticate_scan_token",
    "create_scan_token",
    "digest_token_secret",
    "normalize_expiry_days",
    "normalize_scan_token_label",
    "parse_scan_token",
]
