"""Contracts for bounded execution of pinned local scanner containers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class LocalScannerRun:
    """Normalized files and provenance emitted by one local scan."""

    findings_document: Mapping[str, Any]
    findings_path: Path = field(repr=False)
    scanner_manifest_version: int = 1
    scanner_manifest_digest: str = ""
    scanner_image_digests: Mapping[str, str] = field(default_factory=dict)
    sarif_path: Path | None = field(default=None, repr=False)
    sbom_path: Path | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ScannerRuntimeLimits:
    """Local disk/output ceilings independent of server upload limits."""

    stdout_bytes: int = 16 * 1024 * 1024
    stderr_bytes: int = 1024 * 1024
    findings_bytes: int = 10 * 1024 * 1024
    artifact_bytes: int = 16 * 1024 * 1024


class ScannerRuntimeError(RuntimeError):
    """Docker or scanner execution failed without exposing host paths."""


__all__ = ["LocalScannerRun", "ScannerRuntimeError", "ScannerRuntimeLimits"]
