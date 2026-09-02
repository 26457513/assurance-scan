"""Finding response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FindingResponse(BaseModel):
    """One normalized finding."""

    id: int
    finding_key: str | None = None
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


class SourceLineResponse(BaseModel):
    """One numbered line in an uploaded source window."""

    number: int
    text: str
    truncated: bool


class SourceContextResponse(BaseModel):
    """Finding-scoped source context for either scan origin."""

    available: bool
    provider: str | None = None
    path: str | None = None
    window_start: int | None = None
    window_end: int | None = None
    highlight_start: int | None = None
    highlight_end: int | None = None
    highlight_truncated: bool = False
    lines: list[SourceLineResponse] = Field(default_factory=list)
    source_hash: str | None = None
    redaction_version: int | None = None
    redaction_changed: bool = False
    unavailable_reason: str | None = None
