"""Validation and orchestration for authoritative repository reconciliation."""

from __future__ import annotations

import re
from datetime import datetime

from .models import (
    GithubInstallationSnapshot,
    ReconciliationResult,
    ReconciliationValidationError,
)
from .ports import GithubRepositoryReconciliationPort


_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]{1,100}$")


async def reconcile_github_repositories(
    snapshot: GithubInstallationSnapshot,
    *,
    verified_at: datetime,
    repository: GithubRepositoryReconciliationPort,
) -> ReconciliationResult:
    """Validate one complete installation snapshot before atomic replacement."""
    validate_installation_snapshot(snapshot)
    if verified_at.tzinfo is None or verified_at.utcoffset() is None:
        raise ReconciliationValidationError("verification time must be timezone-aware")
    return await repository.replace(snapshot, verified_at=verified_at)


def validate_installation_snapshot(snapshot: GithubInstallationSnapshot) -> GithubInstallationSnapshot:
    if snapshot.github_installation_id <= 0 or snapshot.github_owner_id <= 0:
        raise ReconciliationValidationError("installation and owner IDs must be positive")
    if not _text(snapshot.owner_login, 128):
        raise ReconciliationValidationError("installation owner login is invalid")
    if snapshot.suspended_at is not None:
        _aware(snapshot.suspended_at, "suspension")
    if snapshot.deleted_at is not None:
        _aware(snapshot.deleted_at, "deletion")
    if snapshot.repositories_etag is not None and not _text(snapshot.repositories_etag, 256):
        raise ReconciliationValidationError("repository ETag is invalid")
    if snapshot.reconciliation_cursor is not None and not _text(snapshot.reconciliation_cursor, 512):
        raise ReconciliationValidationError("reconciliation cursor is invalid")
    seen: set[int] = set()
    for item in snapshot.repositories:
        if item.github_repository_id <= 0 or item.github_repository_id in seen:
            raise ReconciliationValidationError("repository IDs must be unique and positive")
        repository_name = item.full_name.rpartition("/")[2]
        if item.github_owner_id <= 0 or _NAME.fullmatch(item.full_name) is None or repository_name in {".", ".."}:
            raise ReconciliationValidationError("repository identity is invalid")
        if not _text(item.default_branch, 256):
            raise ReconciliationValidationError("repository default branch is invalid")
        seen.add(item.github_repository_id)
    return snapshot


def _text(value: str, maximum: int) -> bool:
    return (
        bool(value)
        and len(value) <= maximum
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReconciliationValidationError(f"{label} time must be timezone-aware")
