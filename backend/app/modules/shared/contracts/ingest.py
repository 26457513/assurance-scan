"""Stable, source-neutral contracts for result ingestion."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Sequence

from .findings import FindingPayload
from .source_context import SourceContextPayload


IngestStatus = Literal["ingested", "exists"]
ScannerStatus = Literal["completed", "failed", "skipped"]


@dataclass(frozen=True)
class ArtifactSpec:
    """Mapping from a protocol part to its persisted artifact kind."""

    part_name: str
    artifact_kind: str
    scanner_kind: str


ARTIFACT_SPECS: tuple[ArtifactSpec, ...] = (
    ArtifactSpec("sarif", "sarif", "assurance-scan/sarif"),
    ArtifactSpec("sbom", "cyclonedx-json", "assurance-scan/sbom"),
    ArtifactSpec("findings", "json", "assurance-scan/findings"),
)

BLOB_ARTIFACTS: tuple[tuple[str, str, str], ...] = tuple(
    (spec.part_name, spec.artifact_kind, spec.scanner_kind) for spec in ARTIFACT_SPECS
)


@dataclass(frozen=True)
class ResolvedProject:
    """Canonical registered project selected before result persistence."""

    project_id: int
    repository: str
    github_repository_id: int | None = None


@dataclass(frozen=True)
class ScannerResult:
    """Source-neutral outcome and reproducibility data for one scanner."""

    kind: str
    status: ScannerStatus
    duration_ms: int | None = None
    image_reference: str | None = None
    image_digest: str | None = None
    tool_version: str | None = None
    database_version: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class ResultBundle:
    """Scanner output only; origin and source provenance are deliberately absent."""

    schema_version: int
    scanners: Sequence[ScannerResult] = ()
    findings: Sequence[FindingPayload] = ()
    source_contexts: Sequence[SourceContextPayload] = ()
    artifacts: Mapping[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True)
class GitHubIngestEnvelope:
    """Authoritative provenance obtained from the GitHub API."""

    project: ResolvedProject
    github_run_id: int
    checkout_sha: str
    head_sha: str
    git_object_format: Literal["sha1", "sha256"]
    branch: str | None
    conclusion: str | None
    started_at: datetime | None
    completed_at: datetime | None
    run_number: int | None = None
    run_attempt: int | None = None
    run_url: str | None = None
    event: str | None = None
    actor: str | None = None
    display_title: str | None = None


@dataclass(frozen=True)
class LocalIngestEnvelope:
    """Server-locked local provenance and authenticated submitting principal."""

    run_id: str
    project: ResolvedProject
    submitted_by_user_id: int
    submitting_token_id: str
    submitting_token_label: str
    payload_hash: str
    commit_sha: str
    git_object_format: Literal["sha1", "sha256"]
    branch: str | None
    working_tree_dirty: bool
    source_content_hash: str
    source_manifest_version: str
    client_provenance_version: int
    client_provenance: Mapping[str, Any]
    started_at: datetime | None
    completed_at: datetime | None


IngestEnvelope = GitHubIngestEnvelope | LocalIngestEnvelope


@dataclass(frozen=True)
class RunRecord:
    """Source-neutral run data ready for atomic persistence."""

    run_id: str
    project_id: int
    origin: str
    options_json: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    commit_sha: str | None
    git_branch: str | None
    error_message: str | None
    findings_json: str | None
    repository_full_name_at_scan: str | None = None
    git_object_format: str | None = None
    working_tree_dirty: bool | None = None
    source_content_hash: str | None = None
    source_manifest_version: str | None = None
    submitted_by_user_id: int | None = None
    submitting_token_id: str | None = None
    payload_hash: str | None = None
    client_provenance_version: int | None = None
    client_provenance_json: str | None = None
    github_run_id: int | None = None
    github_run_number: int | None = None
    github_run_attempt: int | None = None
    github_run_url: str | None = None
    github_event: str | None = None
    github_actor: str | None = None
    github_head_sha: str | None = None
    local_machine_label: str | None = None


__all__ = [
    "ARTIFACT_SPECS",
    "BLOB_ARTIFACTS",
    "ArtifactSpec",
    "GitHubIngestEnvelope",
    "IngestEnvelope",
    "IngestStatus",
    "LocalIngestEnvelope",
    "ResolvedProject",
    "ResultBundle",
    "RunRecord",
    "ScannerResult",
    "ScannerStatus",
]
