"""Browser authentication capability with no web-framework dependency."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from ._adapters import exchange_google_code_http
from .models import GoogleIdentityPayload


def basic_auth_ok(authorization: str | None, user: str, password: str) -> bool:
    """Return whether an Authorization header matches shared credentials."""
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


def mint_session(email: str, secret: str, ttl: int = 30 * 24 * 3600) -> str:
    """Create the existing stateless signed browser-session cookie."""
    body = f"{email}.{int(time.time()) + ttl}"
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_session(value: str | None, secret: str) -> str | None:
    """Validate a signed browser-session cookie and return its email."""
    if not value:
        return None
    parts = value.split(".")
    if len(parts) < 3:
        return None
    sig, exp = parts[-1], parts[-2]
    email = ".".join(parts[:-2])
    body = f"{email}.{exp}"
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if time.time() > int(exp):
        return None
    return email


def exchange_google_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> GoogleIdentityPayload:
    """Exchange a Google authorization code for the consumed ID claims."""
    return exchange_google_code_http(code, client_id, client_secret, redirect_uri)


def allowed_google_account(payload: GoogleIdentityPayload, domain: str) -> bool:
    """Return whether Google claims identify an account in the hosted domain."""
    return bool(payload.get("email")) and payload.get("hd") == domain
