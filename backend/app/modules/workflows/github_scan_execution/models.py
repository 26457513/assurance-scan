"""Contracts for the GitHub Actions scanner workflow."""

from __future__ import annotations

from typing import TypeAlias

from app.modules.atomic.scanning.finding_parser import ParsedFinding


ScanExecutionResult: TypeAlias = tuple[
    list[ParsedFinding],
    dict[str, str],
    dict[str, float],
]


__all__ = ["ScanExecutionResult"]
