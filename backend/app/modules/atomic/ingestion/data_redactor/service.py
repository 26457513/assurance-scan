"""Recursive, deterministic secret and host-path redaction.

This capability is deliberately shared by client and server compositions.  It
never logs or raises with source values, and always builds a detached tree so a
caller cannot accidentally persist the unredacted input through mutation.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .models import JSONValue, RedactionResult


REDACTED = "[REDACTED]"
REDACTED_HOST = "[REDACTED_HOST_PATH]"

_SENSITIVE_KEY = re.compile(
    r"^(?:secret|secret_value|password|passwd|pwd|authorization|proxy_authorization|"
    r"cookie|set_cookie|credential|credentials|private_key|api_key|access_key|"
    r"access_token|refresh_token|client_secret|git_credentials|token)$",
    re.IGNORECASE,
)
_SECRET_PATTERNS = (
    re.compile(r"AS_CANARY_SECRET_DO_NOT_PERSIST(?:_[A-Za-z0-9_-]+)?"),
    re.compile(r"asu_v1_[A-Za-z0-9_-]{16}\.[A-Za-z0-9_-]{43}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)(?:https?|ssh)://[^\s/@:]+:[^\s/@]+@"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.DOTALL,
    ),
)
_UNIX_HOST_PATH = re.compile(r"(?<![\w.])/(?:Users|home)/[^/\s]+(?=/|\b)")
_WINDOWS_HOST_PATH = re.compile(r"(?i)(?<![\w])(?:[A-Z]:\\)?Users\\[^\\\s]+(?=\\|\b)")


def redact_text(value: str, *, repository_root: str | None = None) -> tuple[str, int]:
    """Redact known credential forms and environment-specific path prefixes."""
    redacted = value
    replacements = 0
    if repository_root:
        root = repository_root.rstrip("/\\")
        if root:
            redacted, count = re.subn(re.escape(root) + r"(?=[/\\])", ".", redacted)
            replacements += count
    for pattern in _SECRET_PATTERNS:
        redacted, count = pattern.subn(REDACTED, redacted)
        replacements += count
    redacted, count = _UNIX_HOST_PATH.subn(REDACTED_HOST, redacted)
    replacements += count
    redacted, count = _WINDOWS_HOST_PATH.subn(REDACTED_HOST, redacted)
    replacements += count
    return redacted, replacements


def redact_json(value: JSONValue, *, repository_root: str | None = None) -> RedactionResult:
    """Recursively redact a JSON-compatible tree without mutating the input."""
    normalized_root = _normalize_root(repository_root)
    redacted, replacements = _redact(value, repository_root=normalized_root)
    return RedactionResult(value=redacted, replacements=replacements)


def _redact(value: JSONValue, *, repository_root: str | None) -> tuple[JSONValue, int]:
    if isinstance(value, dict):
        output: dict[str, JSONValue] = {}
        replacements = 0
        for key, item in value.items():
            if _SENSITIVE_KEY.fullmatch(key):
                output[key] = REDACTED
                replacements += 1
                continue
            output[key], count = _redact(item, repository_root=repository_root)
            replacements += count
        return output, replacements
    if isinstance(value, list):
        output_list: list[JSONValue] = []
        replacements = 0
        for item in value:
            clean, count = _redact(item, repository_root=repository_root)
            output_list.append(clean)
            replacements += count
        return output_list, replacements
    if isinstance(value, str):
        return redact_text(value, repository_root=repository_root)
    return value, 0


def _normalize_root(repository_root: str | None) -> str | None:
    if not repository_root:
        return None
    # Do not resolve or touch the host filesystem.  PurePath normalization is
    # sufficient and avoids exposing the root through errors or logs.
    normalized = str(PurePosixPath(repository_root.replace("\\", "/")))
    return normalized if normalized not in {"", "."} else None


__all__ = ["REDACTED", "REDACTED_HOST", "redact_json", "redact_text"]
