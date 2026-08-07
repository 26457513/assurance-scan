"""Scan request and response schemas."""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    """Body for POST /api/scans. All fields optional; defaults to scanning $PWD."""

    project_path: str | None = Field(
        default=None,
        description="Absolute host path to scan. Defaults to the server's $PWD.",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form options echoed into the run record (Phase 1: images, urls, uploads).",
    )


class ScanResponse(BaseModel):
    """Returned immediately on enqueue."""

    run_id: str
    project_path: str
    status: str
    queued_at: dt.datetime


class ScannerStatus(BaseModel):
    kind: str
    status: str
    started_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None
    error_message: str | None = None


class ScanStatus(BaseModel):
    """Detail view for one scan."""

    run_id: str
    project_path: str
    status: str
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    scanner_status: list[ScannerStatus] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class ScanSummary(BaseModel):
    """List view for one scan."""

    run_id: str
    project_path: str
    status: str
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    finding_count: int = 0
