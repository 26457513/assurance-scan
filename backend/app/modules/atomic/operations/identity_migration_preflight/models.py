"""Serializable results for the read-only identity migration preflight."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PreflightConflict:
    code: str
    row_ids: tuple[str, ...]


@dataclass(frozen=True)
class IdentityMigrationPreflight:
    schema: str
    schema_revision: str | None
    linked_user_ids: tuple[int, ...]
    unlinked_user_ids: tuple[int, ...]
    bound_project_ids: tuple[int, ...]
    unbound_project_ids: tuple[int, ...]
    counts: dict[str, int]
    membership_counts: dict[str, int]
    migratable_github_run_ids: tuple[str, ...]
    server_run_ids: tuple[str, ...]
    local_run_ids: tuple[str, ...]
    conflicts: tuple[PreflightConflict, ...]
    blocked: bool
    checksum: str

    def to_document(self) -> dict[str, Any]:
        """Return a JSON-safe report containing no identity labels or payload data."""

        return asdict(self)


__all__ = ["IdentityMigrationPreflight", "PreflightConflict"]
