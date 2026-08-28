"""Contracts for immutable local source snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


SOURCE_MANIFEST_VERSION = "assurance-snapshot-v1"


@dataclass(frozen=True)
class SnapshotLimits:
    max_entries: int = 500_000
    max_file_bytes: int = 1024 * 1024 * 1024
    max_total_bytes: int = 5 * 1024 * 1024 * 1024
    free_space_reserve_bytes: int = 1024 * 1024 * 1024


@dataclass(frozen=True)
class SnapshotEntry:
    path: str
    kind: str
    mode: int
    size: int
    content_hash: str | None = None
    symlink_target: str | None = None


@dataclass(frozen=True)
class SourceSnapshot:
    root: Path
    entries: tuple[SnapshotEntry, ...]
    source_content_hash: str
    source_manifest_version: str
    total_bytes: int
    lfs_state: str
    warnings: tuple[str, ...]


class SnapshotIndexPort(Protocol):
    def included_paths(self, root: Path) -> Sequence[str]:
        """Return tracked/non-ignored paths, recursively expanding initialized submodules."""

    def fingerprint(self, root: Path) -> str:
        """Return a pre/post mutation fingerprint of the indexed working tree."""

    def lfs_paths(self, root: Path) -> Sequence[str]:
        """Return tracked paths governed by Git LFS attributes."""


class SourceSnapshotError(RuntimeError):
    """Snapshot creation failed safely."""


class SourceChangedError(SourceSnapshotError):
    """The checkout changed while its snapshot was being assembled."""


__all__ = [
    "SOURCE_MANIFEST_VERSION",
    "SnapshotEntry",
    "SnapshotIndexPort",
    "SnapshotLimits",
    "SourceChangedError",
    "SourceSnapshot",
    "SourceSnapshotError",
]
