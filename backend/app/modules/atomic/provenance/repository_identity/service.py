"""Deterministic repository identity transformations."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .models import InvalidRepositoryIdentityError


_OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")


def _canonical_pair(path: str, *, original: str) -> str:
    cleaned = path.strip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    parts = cleaned.split("/")
    if (
        len(parts) != 2
        or not _OWNER_RE.fullmatch(parts[0])
        or not _REPOSITORY_RE.fullmatch(parts[1])
        or parts[1] in {".", ".."}
    ):
        raise InvalidRepositoryIdentityError(
            f"expected a GitHub owner/repository reference: {original}"
        )
    return f"{parts[0]}/{parts[1]}"


def parse_github_repository(value: str) -> str | None:
    """Return display-preserving ``owner/repository`` for supported GitHub forms."""
    if not value or not value.strip():
        return None
    candidate = value.strip()
    if candidate.startswith("git@github.com:"):
        return _canonical_pair(candidate.removeprefix("git@github.com:"), original=value)
    if "://" not in candidate:
        return _canonical_pair(candidate, original=value)

    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https", "ssh"}:
        raise InvalidRepositoryIdentityError(f"unsupported repository URL: {value}")
    if parsed.hostname != "github.com" or parsed.port is not None:
        raise InvalidRepositoryIdentityError(f"not a GitHub repository URL: {value}")
    if parsed.query or parsed.fragment:
        raise InvalidRepositoryIdentityError(
            f"repository URL must not contain a query or fragment: {value}"
        )
    if parsed.scheme == "ssh":
        if parsed.username != "git" or parsed.password is not None:
            raise InvalidRepositoryIdentityError(f"invalid GitHub SSH URL: {value}")
    elif parsed.username is not None or parsed.password is not None:
        raise InvalidRepositoryIdentityError(f"invalid GitHub HTTPS URL: {value}")
    return _canonical_pair(parsed.path, original=value)


def normalize_github_repository_key(repository: str) -> str:
    """Return the case-insensitive registry key for a parsed repository."""
    parsed = parse_github_repository(repository)
    if parsed is None:
        raise InvalidRepositoryIdentityError("GitHub repository is required")
    return parsed.casefold()
