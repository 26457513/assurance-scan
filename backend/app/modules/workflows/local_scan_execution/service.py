"""Orchestrate immutable snapshot, scan, outbox, and optional upload steps."""
from __future__ import annotations

import uuid
from typing import Any

from app.modules.atomic.local_cli.upload_client import (
    UploadBundle,
    UploadClientError,
    UploadDisposition,
)

from .models import (
    GitProvenance,
    LocalCLIConfig,
    LocalScanExecutionCommand,
    LocalScanExecutionDependencies,
    LocalScanExecutionOutcome,
    LocalScanExecutionResult,
    ScanOutput,
    SourceSnapshot,
)


def execute_local_scan(
    command: LocalScanExecutionCommand,
    dependencies: LocalScanExecutionDependencies,
) -> LocalScanExecutionResult:
    """Execute or retry a scan while preserving one immutable request bundle."""

    _validate_command(command)
    config = dependencies.config.load()
    if command.retry_request_id is not None:
        if command.no_upload:
            raise ValueError("no-upload cannot be combined with upload retry")
        bundle = dependencies.outbox.load(command.retry_request_id)
        return _upload_or_retain(bundle.request_id, bundle, config, dependencies)

    request_id = command.request_id or str(uuid.uuid4())
    _validate_request_id(request_id)
    provenance = dependencies.git.inspect(command.project_path)
    snapshot = dependencies.snapshots.create(command.project_path, request_id)
    try:
        output = dependencies.scanners.scan(snapshot, request_id)
    finally:
        dependencies.snapshots.cleanup(snapshot)

    metadata = _metadata(
        request_id,
        provenance,
        snapshot,
        output,
        config,
        command,
    )
    bundle = dependencies.outbox.create(request_id, metadata, output)
    if command.no_upload:
        dependencies.outbox.retain(request_id, "no_upload")
        return LocalScanExecutionResult(
            LocalScanExecutionOutcome.SCANNED_ONLY,
            request_id,
        )
    return _upload_or_retain(request_id, bundle, config, dependencies)


def _validate_command(command: LocalScanExecutionCommand) -> None:
    branch = command.branch_override
    if branch is not None and (
        not branch
        or len(branch) > 512
        or "\x00" in branch
        or "\n" in branch
        or "\r" in branch
    ):
        raise ValueError("branch override is invalid")
    if command.request_id is not None:
        _validate_request_id(command.request_id)


def _validate_request_id(request_id: str) -> None:
    try:
        parsed = uuid.UUID(request_id)
    except ValueError as exc:
        raise ValueError("request ID must be a canonical UUIDv4") from exc
    if parsed.version != 4 or str(parsed) != request_id:
        raise ValueError("request ID must be a canonical UUIDv4")


def _upload_or_retain(
    request_id: str,
    bundle: UploadBundle,
    config: LocalCLIConfig,
    dependencies: LocalScanExecutionDependencies,
) -> LocalScanExecutionResult:
    if not config.token:
        dependencies.outbox.retain(request_id, "not_enrolled")
        return LocalScanExecutionResult(
            LocalScanExecutionOutcome.RETAINED,
            request_id,
            error_code="not_enrolled",
        )
    try:
        upload = dependencies.uploader.upload(bundle, config)
    except UploadClientError as exc:
        dependencies.outbox.retain(request_id, exc.code)
        return LocalScanExecutionResult(
            LocalScanExecutionOutcome.RETAINED,
            request_id,
            error_code=exc.code,
        )
    if upload.disposition is UploadDisposition.IN_PROGRESS:
        dependencies.outbox.retain(request_id, "upload_in_progress")
        return LocalScanExecutionResult(
            LocalScanExecutionOutcome.IN_PROGRESS,
            request_id,
            retry_after_seconds=upload.retry_after_seconds,
        )
    dependencies.outbox.mark_uploaded(request_id, upload)
    return LocalScanExecutionResult(
        LocalScanExecutionOutcome.UPLOADED,
        request_id,
        run_id=upload.run_id,
        run_url=upload.run_url,
    )


def _metadata(
    request_id: str,
    provenance: GitProvenance,
    snapshot: SourceSnapshot,
    output: ScanOutput,
    config: LocalCLIConfig,
    command: LocalScanExecutionCommand,
) -> dict[str, Any]:
    project_override = command.project_override or provenance.project_override
    branch = command.branch_override or provenance.branch
    if branch is not None and (
        not branch
        or len(branch) > 512
        or "\x00" in branch
        or "\n" in branch
        or "\r" in branch
    ):
        raise ValueError("branch override is invalid")
    return {
        "schema_version": 1,
        "request_id": request_id,
        "repository": provenance.repository,
        "branch": branch,
        "commit": provenance.commit,
        "git_object_format": provenance.git_object_format,
        "working_tree_dirty": provenance.working_tree_dirty,
        "source_content_hash": snapshot.source_content_hash,
        "source_manifest_version": snapshot.source_manifest_version,
        "installation_id": config.installation_id,
        "cli_version": config.cli_version,
        "cli_build_revision": config.cli_build_revision,
        "cli_image_id": config.cli_image_id,
        "cli_image_digest": config.cli_image_digest,
        "project_override": project_override,
        "scanner_manifest_version": output.scanner_manifest_version,
        "scanner_manifest_digest": output.scanner_manifest_digest,
        "scanner_image_digests": dict(output.scanner_image_digests),
        "lfs_state": snapshot.lfs_state,
        "submodules": list(snapshot.submodules),
    }


__all__ = ["execute_local_scan"]
