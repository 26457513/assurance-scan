"""Focused orchestration tests for local scan execution and outbox retry."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.atomic.local_cli.upload_client import (
    UploadBundle,
    UploadClientError,
    UploadDisposition,
    UploadResult,
)
from app.modules.workflows.local_scan_execution import (
    GitProvenance,
    LocalCLIConfig,
    LocalScanExecutionCommand,
    LocalScanExecutionDependencies,
    LocalScanExecutionOutcome,
    ScanOutput,
    SourceSnapshot,
    execute_local_scan,
)


class Config:
    def __init__(self, token: str | None = "token") -> None:
        self.value = LocalCLIConfig(
            "https://scan.example",
            "018f47a2-4c72-4c9e-9f60-780cb70b8fe4",
            "0.1.0",
            "a" * 40,
            "sha256:" + "b" * 64,
            None,
            token,
        )

    def load(self):
        return self.value


class Git:
    calls = 0

    def inspect(self, project_path: Path):
        self.calls += 1
        return GitProvenance("owner/repo", "main", "c" * 40, "sha1", True)


class Snapshots:
    def __init__(self) -> None:
        self.created = 0
        self.cleaned = 0

    def create(self, project_path: Path, request_id: str):
        self.created += 1
        return SourceSnapshot(request_id, "d" * 64, "assurance-snapshot-v1", "opaque")

    def cleanup(self, snapshot: SourceSnapshot):
        self.cleaned += 1


class Scanners:
    calls = 0

    def scan(self, snapshot: SourceSnapshot, request_id: str):
        self.calls += 1
        return ScanOutput(
            {"schema_version": 1, "scanners": [], "findings": []},
            Path("findings.json"),
            scanner_manifest_digest="e" * 64,
            scanner_image_digests={"semgrep": "semgrep@sha256:" + "f" * 64},
        )


class Outbox:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.created_metadata = None
        self.loaded: list[str] = []
        self.retained: list[tuple[str, str]] = []
        self.uploaded: list[str] = []

    def _bundle(self, request_id: str):
        metadata = self.tmp_path / "metadata.json"
        findings = self.tmp_path / "findings.json"
        metadata.write_text("{}")
        findings.write_text("{}")
        return UploadBundle(request_id, metadata, findings)

    def create(self, request_id, metadata, output):
        self.created_metadata = metadata
        return self._bundle(request_id)

    def load(self, request_id):
        self.loaded.append(request_id)
        return self._bundle(request_id)

    def retain(self, request_id, reason_code):
        self.retained.append((request_id, reason_code))

    def mark_uploaded(self, request_id, result):
        self.uploaded.append(request_id)


class Uploader:
    def __init__(self, result=None, error=None) -> None:
        self.result = result or UploadResult(
            UploadDisposition.UPLOADED,
            201,
            "local-1",
            1,
            "https://scan.example/scans/local-1",
        )
        self.error = error
        self.request_ids: list[str] = []

    def upload(self, bundle, config):
        self.request_ids.append(bundle.request_id)
        if self.error:
            raise self.error
        return self.result


def _dependencies(tmp_path: Path, *, token="token", uploader=None):
    objects = (
        Config(token),
        Git(),
        Snapshots(),
        Scanners(),
        Outbox(tmp_path),
        uploader or Uploader(),
    )
    return LocalScanExecutionDependencies(*objects), objects


def test_scan_snapshots_writes_outbox_then_uploads(tmp_path: Path) -> None:
    dependencies, objects = _dependencies(tmp_path)
    result = execute_local_scan(LocalScanExecutionCommand(tmp_path), dependencies)
    _, _, snapshots, _, outbox, uploader = objects
    assert result.outcome is LocalScanExecutionOutcome.UPLOADED
    assert snapshots.created == snapshots.cleaned == 1
    assert outbox.created_metadata["request_id"] == result.request_id
    assert uploader.request_ids == [result.request_id]
    assert outbox.uploaded == [result.request_id]


def test_no_upload_retains_outbox_without_requiring_token(tmp_path: Path) -> None:
    dependencies, objects = _dependencies(tmp_path, token=None)
    result = execute_local_scan(
        LocalScanExecutionCommand(tmp_path, no_upload=True), dependencies
    )
    outbox, uploader = objects[4], objects[5]
    assert result.outcome is LocalScanExecutionOutcome.SCANNED_ONLY
    assert outbox.retained == [(result.request_id, "no_upload")]
    assert uploader.request_ids == []


def test_retry_loads_exact_bundle_without_git_snapshot_or_scan(tmp_path: Path) -> None:
    request_id = "018f47a2-4c72-4c9e-9f60-780cb70b8fe4"
    dependencies, objects = _dependencies(tmp_path)
    result = execute_local_scan(
        LocalScanExecutionCommand(tmp_path, retry_request_id=request_id),
        dependencies,
    )
    _, git, snapshots, scanners, outbox, uploader = objects
    assert result.request_id == request_id
    assert git.calls == snapshots.created == scanners.calls == 0
    assert outbox.loaded == [request_id]
    assert uploader.request_ids == [request_id]


def test_permanent_upload_failure_retains_same_request(tmp_path: Path) -> None:
    uploader = Uploader(error=UploadClientError("invalid_scan_schema", "upload rejected"))
    dependencies, objects = _dependencies(tmp_path, uploader=uploader)
    result = execute_local_scan(LocalScanExecutionCommand(tmp_path), dependencies)
    outbox = objects[4]
    assert result.outcome is LocalScanExecutionOutcome.RETAINED
    assert result.error_code == "invalid_scan_schema"
    assert outbox.retained == [(result.request_id, "invalid_scan_schema")]


def test_in_progress_upload_retains_bundle_and_retry_after(tmp_path: Path) -> None:
    uploader = Uploader(result=UploadResult(
        UploadDisposition.IN_PROGRESS,
        202,
        None,
        1,
        None,
        retry_after_seconds=23,
    ))
    dependencies, objects = _dependencies(tmp_path, uploader=uploader)
    result = execute_local_scan(LocalScanExecutionCommand(tmp_path), dependencies)
    outbox = objects[4]
    assert result.outcome is LocalScanExecutionOutcome.IN_PROGRESS
    assert result.retry_after_seconds == 23
    assert outbox.retained == [(result.request_id, "upload_in_progress")]


def test_invalid_branch_override_fails_before_snapshot_or_scan(tmp_path: Path) -> None:
    dependencies, objects = _dependencies(tmp_path)

    with pytest.raises(ValueError, match="branch override"):
        execute_local_scan(
            LocalScanExecutionCommand(tmp_path, branch_override="invalid\nbranch"),
            dependencies,
        )

    assert objects[2].created == 0
    assert objects[3].calls == 0
