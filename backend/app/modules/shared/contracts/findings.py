"""Stable finding contracts shared by ingestion capabilities."""
from __future__ import annotations

from typing import Any, TypedDict


class FindingPayload(TypedDict, total=False):
    """Finding shape emitted by the existing CI findings bundle."""

    finding_key: str
    scanner: str
    rule_id: str | None
    severity: str | None
    file_path: str | None
    line_start: int | None
    line_end: int | None
    message: str | None
    theme: str | None
    fix_strategy: str | None
    compliance_tags: list[str]
    package_name: str | None
    package_version: str | None
    package_ecosystem: str | None
    package_purl: str | None


NormalizedFinding = dict[str, Any]
