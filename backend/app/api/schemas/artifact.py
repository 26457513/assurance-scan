"""Generated scan artifact response schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class ArtifactSummary(BaseModel):
    name: str
    filename: str
    description: str
    media_type: str
    status: str
    available: bool
    size_bytes: int | None = None
    content_hash: str | None = None
    created_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None
    download_url: str | None = None


class ArtifactListResponse(BaseModel):
    run_id: str
    retention_days: int
    artifacts: list[ArtifactSummary] = Field(default_factory=list)


class SbomPackage(BaseModel):
    bom_ref: str | None = None
    name: str
    version: str | None = None
    ecosystem: str | None = None
    component_type: str | None = None
    purl: str | None = None
    licenses: list[str] = Field(default_factory=list)
    vulnerability_count: int | None = None


class SbomPackageListResponse(BaseModel):
    run_id: str
    total: int
    packages: list[SbomPackage] = Field(default_factory=list)
