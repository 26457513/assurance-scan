"""Scan request and response schemas."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

ScanOrigin = Literal["github-actions", "local", "server"]


class ScanRequest(BaseModel):
    """Body for POST /api/scans."""

    project_id: int = Field(
        gt=0,
        description="Registered project to scan using its server checkout.",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form options echoed into the run record (Phase 1: images, urls, uploads).",
    )


class ScanResponse(BaseModel):
    """Returned immediately on enqueue."""

    run_id: str
    project_id: int
    origin: ScanOrigin
    status: str
    queued_at: dt.datetime


class ScannerStatus(BaseModel):
    kind: str
    status: str
    duration_seconds: float | None = None
    started_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None
    error_message: str | None = None


class CatalogueRef(BaseModel):
    """Identity of one catalogue snapshot."""

    snapshot_id: str | None = None
    version: str | None = None
    content_hash: str | None = None


class ScanProvenance(BaseModel):
    """What a run evaluated against, and what the project currently has.

    `*_stale` is true when the run's pinned artifact differs from the
    project's latest; None when it can't be determined (nothing pinned or
    nothing current).
    """

    catalogue: CatalogueRef | None = None
    mapping_hash: str | None = None
    current_catalogue: CatalogueRef | None = None
    current_mapping_hash: str | None = None
    catalogue_stale: bool | None = None
    mapping_stale: bool | None = None


class ScanStatus(BaseModel):
    """Detail view for one scan."""

    run_id: str
    project_id: int
    origin: ScanOrigin
    status: str
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    scanner_status: list[ScannerStatus] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    provenance: ScanProvenance | None = None
    git_branch: str | None = None
    commit_sha: str | None = None
    working_tree_dirty: bool | None = None
    repository: str | None = None


class ScanSummary(BaseModel):
    """List view for one scan."""

    # Source-specific display metadata: GitHub workflow number/title or the
    # persisted per-project local sequence and submitting machine label.
    run_number: int | None = None
    event: str | None = None
    actor: str | None = None
    display_title: str | None = None
    git_branch: str | None = None
    commit_sha: str | None = None
    working_tree_dirty: bool | None = None
    repository: str | None = None

    run_id: str
    project_id: int
    origin: ScanOrigin
    status: str
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    finding_count: int = 0
