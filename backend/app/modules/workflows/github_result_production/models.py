"""Commands and ports for producing a GitHub Actions v2 result bundle."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.atomic.scanning.result_producer import ProducedEnvelope
from app.modules.workflows.github_scan_execution import ScanExecutionResult


@dataclass(frozen=True)
class GitHubResultProductionCommand:
    project_root: Path = field(repr=False)
    output_root: Path = field(repr=False)
    scanner_snapshot_path: str = field(repr=False)
    environment: Mapping[str, str] = field(repr=False)
    application_image: str | None = None


@dataclass(frozen=True)
class GitHubResultProductionResult:
    envelope: ProducedEnvelope
    output_root: Path = field(repr=False)
    scan: ScanExecutionResult = field(repr=False)

    @property
    def finding_count(self) -> int:
        return len(self.scan.findings)


GitHubScannerPort = Callable[[str, str | None, Path | None], Awaitable[ScanExecutionResult]]


__all__ = [
    "GitHubResultProductionCommand",
    "GitHubResultProductionResult",
    "GitHubScannerPort",
]
