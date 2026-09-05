"""Structural contract accepted by scanner result builders."""
from __future__ import annotations

from typing import Protocol


class Finding(Protocol):
    """Finding fields required by SARIF, summary, and CI payload rendering."""

    scanner_kind: str
    rule_id: str | None
    severity: str
    file_path: str | None
    line_start: int | None
    line_end: int | None
    message: str
    theme: str | None
    fix_strategy: str | None
    compliance_tags: tuple[str, ...]
    package_name: str | None
    package_version: str | None
    package_ecosystem: str | None
    package_purl: str | None
