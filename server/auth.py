"""Shared-credential Basic Auth for hosted deployments.

Disabled unless APP_AUTH_USER and APP_AUTH_PASSWORD are both set; browsers
prompt once and cache per session, so CI deep links keep working.
"""
from __future__ import annotations

import base64
import hmac


def basic_auth_ok(authorization: str | None, user: str, password: str) -> bool:
    """True when the Authorization header carries these credentials."""
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    supplied_user, sep, supplied_password = decoded.partition(":")
    return hmac.compare_digest(supplied_user, user) and (
        sep == ":" and hmac.compare_digest(supplied_password, password)
    )
