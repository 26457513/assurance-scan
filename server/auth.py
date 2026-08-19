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


# --- Google Workspace login ------------------------------------------------

import hashlib
import json
import time
import urllib.parse
import urllib.request

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def mint_session(email: str, secret: str, ttl: int = 30 * 24 * 3600) -> str:
    """Signed cookie value: email.expiry.hmac — stateless, survives restarts."""
    body = f"{email}.{int(time.time()) + ttl}"
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_session(value: str | None, secret: str) -> str | None:
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


def exchange_google_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    """Exchange an auth code; returns the decoded id_token payload.

    The payload arrives over TLS directly from Google's token endpoint, so
    trusting it here is the standard server-side shortcut.
    """
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        tokens = json.loads(resp.read())
    payload_b64 = tokens["id_token"].split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64))


def allowed_google_account(payload: dict, domain: str) -> bool:
    """Workspace accounts carry hd == the hosted domain; consumers don't."""
    return bool(payload.get("email")) and payload.get("hd") == domain
