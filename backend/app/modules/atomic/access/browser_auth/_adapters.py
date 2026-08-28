"""Private HTTP adapter for the Google authorization-code exchange."""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request

from .models import GOOGLE_TOKEN_URL, GoogleIdentityPayload


def exchange_google_code_http(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> GoogleIdentityPayload:
    """Perform the Google token-endpoint request and decode its ID claims."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=data, method="POST")
    if req.full_url != GOOGLE_TOKEN_URL:
        raise ValueError("unexpected Google token endpoint")
    with urllib.request.urlopen(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        req, timeout=15
    ) as resp:
        tokens = json.loads(resp.read())
    payload_b64 = tokens["id_token"].split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64))
