"""Serializable result for the journalled identity cutover."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class IdentityCutoverResult:
    status: str
    preflight_checksum: str
    state_checksum: str
    completed_phases: tuple[str, ...]
    counts: dict[str, int]
    database_bytes: int
    required_free_bytes: int
    available_free_bytes: int
    duration_ms: int

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


class IdentityCutoverError(RuntimeError):
    """A fail-closed cutover invariant was not satisfied."""
