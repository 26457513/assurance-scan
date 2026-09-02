"""Typed inputs and output for source-neutral v2 scan result production."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from app.modules.atomic.scanning.finding_parser import ParsedFinding


ScannerStatus = Literal["completed", "failed", "skipped"]
ScannerErrorCode = Literal[
    "scanner_dependency_failed",
    "scanner_exit_nonzero",
    "scanner_not_configured",
    "scanner_output_invalid",
    "scanner_timeout",
    "scanner_unsupported",
]


@dataclass(frozen=True)
class RepositoryProvenance:
    full_name: str
    commit: str
    git_object_format: Literal["sha1", "sha256"]
    branch: str | None
    working_tree_dirty: bool


@dataclass(frozen=True)
class SourceProvenance:
    snapshot_root: Path
    content_hash: str
    manifest_version: str
    lfs_state: Literal["none", "pointers", "hydrated", "mixed"]
    submodules: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class ScannerRelease:
    manifest_version: int
    manifest_digest: str
    images: Mapping[str, str]


@dataclass(frozen=True)
class ScannerOutcome:
    kind: str
    status: ScannerStatus
    duration_ms: int
    image: str | None
    tool_version: str | None
    database_version: str | None = None
    error_code: ScannerErrorCode | None = None


@dataclass(frozen=True)
class LocalProducerIdentity:
    request_id: str
    cli_installation_id: str
    cli_version: str
    cli_build_revision: str
    cli_image: str


@dataclass(frozen=True)
class GitHubProducerIdentity:
    repository_id: int
    repository_owner_id: int
    run_id: int
    run_number: int
    run_attempt: int
    workflow_ref: str
    workflow_sha: str
    actor: str
    actor_id: int


ProducerIdentity = LocalProducerIdentity | GitHubProducerIdentity


@dataclass(frozen=True)
class ProduceEnvelopeCommand:
    repository: RepositoryProvenance
    source: SourceProvenance
    scanner_release: ScannerRelease
    producer: ProducerIdentity
    scanner_outcomes: tuple[ScannerOutcome, ...]
    findings: tuple[ParsedFinding, ...]
    sarif: bool = True
    sbom: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ProducedEnvelope:
    documents: Mapping[str, Mapping[str, Any]]
    canonical_parts: Mapping[str, bytes]
    payload_hash: str


__all__ = [
    "GitHubProducerIdentity",
    "LocalProducerIdentity",
    "ProduceEnvelopeCommand",
    "ProducedEnvelope",
    "RepositoryProvenance",
    "ScannerErrorCode",
    "ScannerOutcome",
    "ScannerRelease",
    "ScannerStatus",
    "SourceProvenance",
]
