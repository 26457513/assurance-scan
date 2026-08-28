"""Source-neutral contracts for result-bundle ingestion."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Mapping


IngestStatus = Literal["ingested", "exists"]


@dataclass(frozen=True)
class ArtifactSpec:
    """Mapping from an uploaded blob name to its persisted artifact kind."""

    suffix: str
    artifact_kind: str
    description: str


ARTIFACT_SPECS: tuple[ArtifactSpec, ...] = (
    ArtifactSpec("sarif", "sarif", "assurance-scan/sarif"),
    ArtifactSpec("sbom", "cyclonedx-json", "assurance-scan/sbom"),
    ArtifactSpec("findings", "json", "assurance-scan/findings"),
)

BLOB_ARTIFACTS: tuple[tuple[str, str, str], ...] = tuple(
    (spec.suffix, spec.artifact_kind, spec.description) for spec in ARTIFACT_SPECS
)


@dataclass(frozen=True)
class ResolvedGitHubProject:
    """Visible registry identity resolved from a canonical GitHub repository."""

    project_id: int
    repository: str


@dataclass(frozen=True)
class ResultBundle:
    """Boundary inputs used by ingestion workflows."""

    payload: dict[str, Any] | None
    metadata: Mapping[str, Any]
    blobs: Mapping[str, bytes]


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
