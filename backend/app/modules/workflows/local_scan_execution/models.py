"""Commands, results, and injectable ports for container-local scan execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol

from app.modules.atomic.local_cli.upload_client import UploadBundle, UploadResult


@dataclass(frozen=True)
class LocalCLIConfig:
    api_base_url: str
    installation_id: str
    cli_version: str
    cli_build_revision: str
    cli_image_id: str
    cli_image_digest: str | None
    token: str | None = field(default=None, repr=False)
    custom_ca_file: Path | None = field(default=None, repr=False)
    allow_loopback_http: bool = False


@dataclass(frozen=True)
class GitProvenance:
    repository: str
    branch: str | None
    commit: str
    git_object_format: str
    working_tree_dirty: bool
    project_override: str | None = None


@dataclass(frozen=True)
class SourceSnapshot:
    request_id: str
    source_content_hash: str
    source_manifest_version: str
    opaque_handle: str = field(repr=False)
    scanner_handle: str | None = field(default=None, repr=False)
    lfs_state: str = "none"
    submodules: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class ScanOutput:
    findings_document: Mapping[str, Any]
    findings_path: Path = field(repr=False)
    scanner_manifest_version: int = 1
    scanner_manifest_digest: str = ""
    scanner_image_digests: Mapping[str, str] = field(default_factory=dict)
    sarif_path: Path | None = field(default=None, repr=False)
    sbom_path: Path | None = field(default=None, repr=False)


@dataclass(frozen=True)
class LocalScanExecutionCommand:
    project_path: Path = field(repr=False)
    no_upload: bool = False
    retry_request_id: str | None = None
    branch_override: str | None = None
    project_override: str | None = None
    request_id: str | None = None


class LocalScanExecutionOutcome(StrEnum):
    UPLOADED = "uploaded"
    SCANNED_ONLY = "scanned_only"
    RETAINED = "retained"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True)
class LocalScanExecutionResult:
    outcome: LocalScanExecutionOutcome
    request_id: str
    run_id: str | None = None
    run_url: str | None = None
    error_code: str | None = None
    retry_after_seconds: int | None = None


class LocalConfigPort(Protocol):
    def load(self) -> LocalCLIConfig: ...


class GitProvenancePort(Protocol):
    def inspect(self, project_path: Path) -> GitProvenance: ...


class SourceSnapshotPort(Protocol):
    def create(self, project_path: Path, request_id: str) -> SourceSnapshot: ...

    def cleanup(self, snapshot: SourceSnapshot) -> None: ...


class LocalScannerRunnerPort(Protocol):
    def scan(self, snapshot: SourceSnapshot, request_id: str) -> ScanOutput: ...


class LocalOutboxPort(Protocol):
    def create(
        self,
        request_id: str,
        metadata: Mapping[str, Any],
        output: ScanOutput,
    ) -> UploadBundle: ...

    def load(self, request_id: str) -> UploadBundle: ...

    def retain(self, request_id: str, reason_code: str) -> None: ...

    def mark_uploaded(self, request_id: str, result: UploadResult) -> None: ...


class LocalUploadPort(Protocol):
    def upload(self, bundle: UploadBundle, config: LocalCLIConfig) -> UploadResult: ...


@dataclass(frozen=True)
class LocalScanExecutionDependencies:
    config: LocalConfigPort
    git: GitProvenancePort
    snapshots: SourceSnapshotPort
    scanners: LocalScannerRunnerPort
    outbox: LocalOutboxPort
    uploader: LocalUploadPort


__all__ = [
    "GitProvenance",
    "GitProvenancePort",
    "LocalCLIConfig",
    "LocalConfigPort",
    "LocalOutboxPort",
    "LocalScanExecutionCommand",
    "LocalScanExecutionDependencies",
    "LocalScanExecutionOutcome",
    "LocalScanExecutionResult",
    "LocalScannerRunnerPort",
    "LocalUploadPort",
    "ScanOutput",
    "SourceSnapshot",
    "SourceSnapshotPort",
]
