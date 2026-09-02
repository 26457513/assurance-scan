"""Contracts for the GitHub Actions scanner workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any

from app.modules.atomic.scanning.finding_parser import ParsedFinding
from app.modules.atomic.scanning.result_producer import ScannerOutcome


@dataclass(frozen=True)
class ScanExecutionResult:
    findings: tuple[ParsedFinding, ...]
    scanner_outcomes: tuple[ScannerOutcome, ...]
    sbom: Mapping[str, Any] | None


__all__ = ["ScanExecutionResult"]
