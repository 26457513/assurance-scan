"""Fixed-origin JWKS transport and RSA verification for GitHub Actions OIDC."""

from __future__ import annotations

import base64
import datetime as dt
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.modules.shared.contracts.ingest_v2 import OIDC_POLICY_V2


_MAX_JWKS_BYTES = 64 * 1024
_UNKNOWN_KID_REFRESH_COOLDOWN = dt.timedelta(minutes=1)


class GithubOidcInfrastructureError(RuntimeError):
    """GitHub signing keys could not be obtained safely."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class _CachedJwks:
    document: dict[str, Any]
    expires_at: dt.datetime


class GithubOidcJwksClient:
    """Cache the fixed GitHub JWKS for at most the frozen one-hour lifetime."""

    def __init__(self) -> None:
        self._cache: _CachedJwks | None = None
        self._lock = threading.Lock()
        self._unknown_refresh_after: dt.datetime | None = None

    def get(self, *, now: dt.datetime, required_kid: str | None = None) -> Mapping[str, Any]:
        current = _aware(now)
        with self._lock:
            cached = self._cache
            if cached is not None and cached.expires_at > current:
                if required_kid is None or _contains_kid(cached.document, required_kid):
                    return cached.document
                if (
                    self._unknown_refresh_after is not None
                    and self._unknown_refresh_after > current
                ):
                    return cached.document
            document = _fetch_jwks()
            self._cache = _CachedJwks(
                document=document,
                expires_at=current
                + dt.timedelta(seconds=OIDC_POLICY_V2.jwks_cache_seconds),
            )
            self._unknown_refresh_after = (
                current + _UNKNOWN_KID_REFRESH_COOLDOWN
                if required_kid is not None and not _contains_kid(document, required_kid)
                else None
            )
            return document


class CryptographyRsaSignatureVerifier:
    """Verify RS256 signatures against a validated RSA signing JWK."""

    def verify(
        self,
        *,
        signing_input: bytes,
        signature: bytes,
        jwk: Mapping[str, Any],
    ) -> bool:
        try:
            modulus = _base64url_integer(jwk["n"])
            exponent = _base64url_integer(jwk["e"])
            public_key = rsa.RSAPublicNumbers(exponent, modulus).public_key()
            if public_key.key_size < 2048 or public_key.key_size > 8192:
                return False
            public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        except (InvalidSignature, KeyError, TypeError, ValueError):
            return False
        return True


def _fetch_jwks() -> dict[str, Any]:
    request = urllib.request.Request(
        OIDC_POLICY_V2.jwks_url,
        headers={"Accept": "application/json", "User-Agent": "assurance-scan"},
        method="GET",
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=10) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            if response.geturl() != OIDC_POLICY_V2.jwks_url:
                raise GithubOidcInfrastructureError("GitHub JWKS redirected")
            raw = response.read(_MAX_JWKS_BYTES + 1)
    except (OSError, urllib.error.HTTPError) as exc:
        raise GithubOidcInfrastructureError("GitHub JWKS unavailable") from exc
    if len(raw) > _MAX_JWKS_BYTES:
        raise GithubOidcInfrastructureError("GitHub JWKS exceeded the safety limit")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GithubOidcInfrastructureError("GitHub JWKS was invalid JSON") from exc
    if not isinstance(document, dict):
        raise GithubOidcInfrastructureError("GitHub JWKS was not an object")
    return document


def _contains_kid(document: Mapping[str, Any], kid: str) -> bool:
    keys = document.get("keys")
    return isinstance(keys, list) and any(
        isinstance(key, Mapping) and key.get("kid") == kid for key in keys
    )


def _base64url_integer(value: object) -> int:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid JWK integer")
    try:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid JWK integer") from exc
    if not raw or raw[0] == 0:
        raise ValueError("non-canonical JWK integer")
    return int.from_bytes(raw, "big")


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


__all__ = [
    "CryptographyRsaSignatureVerifier",
    "GithubOidcInfrastructureError",
    "GithubOidcJwksClient",
]
