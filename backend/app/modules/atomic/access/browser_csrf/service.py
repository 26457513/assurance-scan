"""Framework-independent signed double-submit CSRF operations."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit


# Version the browser cookie name so an older path-scoped cookie cannot shadow
# the current double-submit value after a deployment. Keep the cookie host-only
# by omitting Domain at the HTTP boundary.
CSRF_COOKIE_NAME = "as_scan_token_csrf_v2"
_TOKEN_TTL_SECONDS = 60 * 60


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    default_port = 80 if parsed.scheme == "http" else 443
    authority = parsed.hostname if port in {None, default_port} else f"{parsed.hostname}:{port}"
    return f"{parsed.scheme}://{authority}"


def _signature(body: str, *, user_key: str, secret: str) -> str:
    message = f"{user_key}\0{body}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def mint_csrf_token(
    *, user_key: str, secret: str, now: int | None = None
) -> str:
    """Mint a short-lived token bound to one authenticated browser user."""
    issued_at = int(time.time()) if now is None else now
    nonce = base64.urlsafe_b64encode(secrets.token_bytes(24)).rstrip(b"=").decode()
    body = f"{nonce}.{issued_at + _TOKEN_TTL_SECONDS}"
    return f"{body}.{_signature(body, user_key=user_key, secret=secret)}"


def validate_csrf_request(
    *,
    cookie_token: str | None,
    header_token: str | None,
    request_origin: str | None,
    public_base_url: str,
    user_key: str,
    secret: str,
    now: int | None = None,
) -> bool:
    """Validate exact origin, double submission, signature, user, and expiry."""
    expected_origin = _origin(public_base_url)
    if (
        expected_origin is None
        or request_origin is None
        or _origin(request_origin) != expected_origin
        or not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        return False
    parts = cookie_token.split(".")
    if len(parts) != 3:
        return False
    nonce, expiry, supplied_signature = parts
    if not nonce or not expiry.isascii() or not expiry.isdecimal():
        return False
    body = f"{nonce}.{expiry}"
    expected_signature = _signature(body, user_key=user_key, secret=secret)
    current_time = int(time.time()) if now is None else now
    return hmac.compare_digest(supplied_signature, expected_signature) and (
        current_time <= int(expiry)
    )
