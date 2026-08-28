"""Immutable local source snapshot capability."""

from .models import (
    SOURCE_MANIFEST_VERSION,
    SnapshotEntry,
    SnapshotIndexPort,
    SnapshotLimits,
    SourceChangedError,
    SourceSnapshot,
    SourceSnapshotError,
)
from .service import canonical_snapshot_hash, create_source_snapshot
from ._adapters import GitSnapshotIndex

__all__ = [
    "SOURCE_MANIFEST_VERSION",
    "SnapshotEntry",
    "SnapshotIndexPort",
    "SnapshotLimits",
    "GitSnapshotIndex",
    "SourceChangedError",
    "SourceSnapshot",
    "SourceSnapshotError",
    "canonical_snapshot_hash",
    "create_source_snapshot",
]
