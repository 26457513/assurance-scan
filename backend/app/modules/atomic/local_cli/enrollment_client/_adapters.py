"""Certificate-verifying stdlib client for the token identity endpoint."""

from __future__ import annotations

import http.client
import json
import ssl
from urllib.parse import urlsplit

from app.modules.atomic.local_cli.config_store import validate_api_url

from .models import EnrollmentConfig, EnrollmentError, TokenIdentity


_MAX_RESPONSE_BYTES = 64 * 1024


def validate_token_identity(config: EnrollmentConfig) -> TokenIdentity:
    """Validate one token at its fixed-origin whoami endpoint."""
    origin = validate_api_url(config.api_url, allow_insecure_loopback=config.allow_loopback_http)
    parsed = urlsplit(origin)
    if parsed.hostname is None:
        raise EnrollmentError("server origin is invalid")
    try:
        if parsed.scheme == "https":
            context = ssl.create_default_context(
                cafile=None if config.custom_ca_file is None else str(config.custom_ca_file)
            )
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
                parsed.hostname,
                parsed.port,
                timeout=15,
                context=context,
            )
        else:
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=15)
        try:
            connection.request(
                "GET",
                "/api/v1/ingest/whoami",
                headers={
                    "Authorization": f"Bearer {config.token}",
                    "Accept": "application/json, application/problem+json",
                },
            )
            response = connection.getresponse()
            body = response.read(_MAX_RESPONSE_BYTES + 1)
        finally:
            connection.close()
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise EnrollmentError("token validation request failed") from exc
    if len(body) > _MAX_RESPONSE_BYTES:
        raise EnrollmentError("token validation response was too large")
    if response.status != 200:
        raise EnrollmentError("token was rejected by the server")
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnrollmentError("token validation response was invalid") from exc
    if not isinstance(document, dict):
        raise EnrollmentError("token validation response was invalid")
    account = document.get("account")
    label = document.get("token_label")
    scopes = document.get("scopes")
    expires_at = document.get("expires_at")
    if (
        not isinstance(account, str)
        or not isinstance(label, str)
        or not isinstance(scopes, list)
        or not all(isinstance(scope, str) for scope in scopes)
        or not isinstance(expires_at, str)
        or "scans:upload" not in scopes
    ):
        raise EnrollmentError("token validation response was invalid")
    return TokenIdentity(account, label, tuple(scopes), expires_at)


__all__ = ["validate_token_identity"]
