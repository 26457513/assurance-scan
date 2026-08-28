"""Compatibility exports for browser authentication.

New code imports from ``app.modules.atomic.access.browser_auth``. Existing
callers keep this stable path during the behavior-preserving module migration.
"""

from app.modules.atomic.access.browser_auth import (
    GOOGLE_AUTH_URL,
    GOOGLE_TOKEN_URL,
    GoogleIdentityPayload,
    allowed_google_account,
    basic_auth_ok,
    exchange_google_code,
    mint_session,
    verify_session,
)

__all__ = [
    "GOOGLE_AUTH_URL",
    "GOOGLE_TOKEN_URL",
    "GoogleIdentityPayload",
    "allowed_google_account",
    "basic_auth_ok",
    "exchange_google_code",
    "mint_session",
    "verify_session",
]
