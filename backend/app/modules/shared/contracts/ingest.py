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
class ResultBundle:
    """Boundary inputs used by ingestion workflows."""

    payload: dict[str, Any] | None
    metadata: Mapping[str, Any]
    blobs: Mapping[str, bytes]


@dataclass(frozen=True)
class RunRecord:
    """Source-neutral run data ready for atomic persistence."""

    run_id: str
    project_path: str
    options_json: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    commit_sha: str | None
    git_branch: str | None
    error_message: str | None
    findings_json: str | None
