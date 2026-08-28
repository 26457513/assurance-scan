"""Finding response schemas."""
from __future__ import annotations

from pydantic import BaseModel


class FindingResponse(BaseModel):
    """One normalized finding."""

    id: int
    run_id: str
    scanner_kind: str
    rule_id: str | None
    severity: str
    file_path: str | None
    line_start: int | None
    line_end: int | None
    message: str
    theme: str | None
    fix_strategy: str | None
    compliance_tags: list[str]


class FindingsListResponse(BaseModel):
    """Wrapped finding list with summary metadata."""

    run_id: str
    total: int
    by_severity: dict[str, int]
    by_scanner: dict[str, int]
    findings: list[FindingResponse]
