"""Issue high-entropy, single-use GitHub sign-in and PKCE material."""

from __future__ import annotations

import base64
import hashlib
import re
import urllib.parse
import uuid
from datetime import datetime, timedelta
from typing import Protocol

from .models import GithubSigninMaterial


SIGNIN_TTL = timedelta(minutes=10)
ALLOWED_RETURN_ROOTS = frozenset(
    {
        "admin",
        "compliance",
        "fix",
        "frs",
        "help",
        "integrations",
        "projects",
        "regimes",
        "scans",
        "settings",
        "setup",
        "trends",
    }
)
MAX_RETURN_PATH_LENGTH = 512
_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


class GithubSigninRandomPort(Protocol):
    def random_bytes(self, size: int) -> bytes: ...


def issue_github_signin(
    *, return_path: str, now: datetime, random: GithubSigninRandomPort
) -> GithubSigninMaterial:
    if not _is_allowed_return_path(return_path):
        raise ValueError("GitHub sign-in return path is not allowlisted")
    if now.tzinfo is None or now.utcoffset() is None:
        raise RuntimeError("GitHub sign-in timestamp must be timezone-aware")
    transaction_cookie = _encode(_random(random, 32))
    state = _encode(_random(random, 32))
    verifier = _encode(_random(random, 64))
    challenge = _encode(hashlib.sha256(verifier.encode("ascii")).digest())
    uuid_bytes = bytearray(_random(random, 16))
    uuid_bytes[6] = (uuid_bytes[6] & 0x0F) | 0x40
    uuid_bytes[8] = (uuid_bytes[8] & 0x3F) | 0x80
    return GithubSigninMaterial(
        transaction_id=str(uuid.UUID(bytes=bytes(uuid_bytes))),
        transaction_cookie=transaction_cookie,
        transaction_digest=digest_signin_value(transaction_cookie),
        state=state,
        state_digest=digest_signin_value(state),
        pkce_verifier=verifier,
        pkce_challenge=challenge,
        return_path=return_path,
        created_at=now,
        expires_at=now + SIGNIN_TTL,
    )


def digest_signin_value(value: str) -> bytes:
    if not isinstance(value, str) or _VALUE_PATTERN.fullmatch(value) is None:
        raise ValueError("GitHub sign-in proof has an invalid format")
    return hashlib.sha256(value.encode("ascii")).digest()


def _is_allowed_return_path(value: str) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_RETURN_PATH_LENGTH:
        return False
    if "\\" in value or any(ord(character) < 32 for character in value):
        return False
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return False
    if parsed.path == "/":
        return True
    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return False
    root = parsed.path.split("/", maxsplit=2)[1]
    return root in ALLOWED_RETURN_ROOTS


def _random(random: GithubSigninRandomPort, size: int) -> bytes:
    value = random.random_bytes(size)
    if not isinstance(value, bytes) or len(value) != size:
        raise RuntimeError(f"random port returned invalid {size}-byte value")
    return value


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
