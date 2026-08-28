"""Use-case sequencing for one authenticated local result upload."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from app.modules.atomic.access.project_authorization import (
    LocalScanProjectContext,
    authorize_local_scan_upload,
)
from app.modules.atomic.ingestion.idempotency_guard import (
    ClaimCommand,
    ClaimDecision,
    acquire_claim,
    claim_handle,
)
from app.modules.atomic.ingestion.usage_quota import (
    QuotaCommand,
    QuotaDecision,
    reserve_usage,
)
from app.modules.shared.contracts.ingest import LocalIngestEnvelope

from app.modules.workflows.result_ingest import (
    build_local_result_bundle,
    ingest_result_bundle,
)

from .models import (
    LocalScanCommand,
    LocalScanDependencies,
    LocalScanIngestError,
    LocalScanOutcome,
    LocalScanResult,
)


async def ingest_local_scan(
    command: LocalScanCommand,
    dependencies: LocalScanDependencies,
    *,
    now: datetime | None = None,
) -> LocalScanResult:
    """Resolve, authorize, claim, redact, and atomically persist one bundle."""
    timestamp = now or datetime.now(timezone.utc)
    metadata = command.metadata
    detected_repository = str(metadata["repository"])
    selector = str(metadata.get("project_override") or detected_repository)
    resolution = await dependencies.projects.resolve(selector)
    if resolution.hidden:
        raise _error(404, "project_not_found", "Project not found", "The project is not available.")
    if resolution.project is None:
        raise _error(
            409,
            "project_not_registered",
            "Project is not registered",
            "Register the repository in Assurance Scan before uploading local results.",
        )
    project = resolution.project
    authorization = authorize_local_scan_upload(
        LocalScanProjectContext(
            user_active=True,
            token_scopes=command.token_scopes,
            project_registered=True,
            project_hidden=False,
        )
    )
    if not authorization.allowed:
        raise _error(403, "project_forbidden", "Project upload is forbidden", authorization.reason)

    quota_command = QuotaCommand(
        user_id=command.user_id,
        token_id=command.token_id,
        client_request_id=command.request_id,
        accepted_bytes=command.accepted_bytes,
    )
    quota = await reserve_usage(
        quota_command,
        repository=dependencies.quotas,
        now=timestamp,
        limits=dependencies.usage_limits,
    )
    if not quota.allowed:
        raise _quota_error(quota.decision, quota.retry_after_seconds)

    claim_command = ClaimCommand(
        user_id=command.user_id,
        token_id=command.token_id,
        client_request_id=command.request_id,
        project_id=project.project_id,
        payload_hash=command.payload_hash,
        accepted_bytes=command.accepted_bytes,
    )
    claim_result = await acquire_claim(
        claim_command,
        repository=dependencies.claims,
        now=timestamp,
    )
    if claim_result.decision is ClaimDecision.REPLAY:
        return _result(
            LocalScanOutcome.REPLAYED,
            claim_result.run_id,
            project.project_id,
            project.repository,
            command.public_base_url,
        )
    if claim_result.decision is ClaimDecision.IN_PROGRESS:
        retry_after = _retry_after(claim_result.lease_expires_at, timestamp)
        return LocalScanResult(
            outcome=LocalScanOutcome.IN_PROGRESS,
            run_id=None,
            project_id=project.project_id,
            repository=project.repository,
            run_url=None,
            status="processing",
            status_url=_request_url(command.public_base_url, command.request_id),
            retry_after_seconds=retry_after,
        )
    if claim_result.decision is ClaimDecision.CONFLICT:
        raise _error(
            409,
            "idempotency_conflict",
            "Idempotency key conflict",
            "The request ID is already bound to different scan content or a different project.",
        )
    if claim_result.decision is ClaimDecision.TOMBSTONED:
        raise _error(
            410,
            "idempotency_tombstoned",
            "Scan request is no longer available",
            "This request ID belongs to a deleted scan and cannot yet be reused.",
        )

    claim = claim_handle(claim_command, claim_result)
    dependencies.persistence.bind_claim(claim)
    run_id = f"local-{uuid.uuid4()}"
    envelope = LocalIngestEnvelope(
        run_id=run_id,
        project=project,
        submitted_by_user_id=command.user_id,
        submitting_token_id=command.token_id,
        payload_hash=command.payload_hash,
        commit_sha=str(metadata["commit"]),
        git_object_format=metadata["git_object_format"],
        branch=metadata.get("branch"),
        working_tree_dirty=bool(metadata["working_tree_dirty"]),
        source_content_hash=str(metadata["source_content_hash"]),
        source_manifest_version=str(metadata["source_manifest_version"]),
        client_provenance_version=1,
        client_provenance=_client_provenance(metadata, detected_repository),
        started_at=timestamp,
        completed_at=timestamp,
    )
    artifacts = {"findings": command.findings_bytes}
    if command.sarif_bytes is not None:
        artifacts["sarif"] = command.sarif_bytes
    if command.sbom_bytes is not None:
        artifacts["sbom"] = command.sbom_bytes
    bundle = build_local_result_bundle(command.findings, artifacts)
    try:
        await ingest_result_bundle(dependencies.persistence, envelope, bundle)
    except BaseException:
        # Result persistence has already rolled its transaction back. Mark the
        # still-fenced claim retryable; a lost worker cannot overwrite it.
        await dependencies.claims.fail(claim, now=datetime.now(timezone.utc))
        raise
    return _result(
        LocalScanOutcome.CREATED,
        run_id,
        project.project_id,
        project.repository,
        command.public_base_url,
    )


def _client_provenance(metadata: Mapping[str, Any], detected_repository: str) -> dict[str, Any]:
    keys = (
        "installation_id",
        "cli_version",
        "cli_build_revision",
        "cli_image_id",
        "cli_image_digest",
        "project_override",
        "scanner_manifest_version",
        "scanner_manifest_digest",
        "scanner_image_digests",
        "lfs_state",
        "submodules",
    )
    return {
        "schema_version": 1,
        "detected_repository": detected_repository,
        **{key: metadata[key] for key in keys if key in metadata},
    }


def _quota_error(decision: QuotaDecision, retry_after: int | None) -> LocalScanIngestError:
    if decision in {QuotaDecision.USER_RETAINED_STORAGE, QuotaDecision.INSTANCE_RETAINED_STORAGE}:
        return LocalScanIngestError(
            status=507,
            code="storage_quota_exceeded",
            title="Retained storage quota exceeded",
            detail="Delete retained scan data or wait for retention cleanup before retrying.",
        )
    if decision is QuotaDecision.DISABLED:
        return _error(503, "local_ingest_disabled", "Local ingest is disabled", "Local ingest is disabled.")
    return LocalScanIngestError(
        status=429,
        code="upload_quota_exceeded",
        title="Upload quota exceeded",
        detail="The local upload rate or concurrency limit has been reached.",
        retryable=True,
        retry_after_seconds=retry_after,
    )


def _error(status: int, code: str, title: str, detail: str) -> LocalScanIngestError:
    return LocalScanIngestError(status=status, code=code, title=title, detail=detail)


def _result(
    outcome: LocalScanOutcome,
    run_id: str | None,
    project_id: int,
    repository: str,
    public_base_url: str,
) -> LocalScanResult:
    run_url = None if run_id is None else f"{public_base_url.rstrip('/')}/scans/{run_id}"
    return LocalScanResult(outcome, run_id, project_id, repository, run_url, "completed")


def _request_url(public_base_url: str, request_id: str) -> str:
    return f"{public_base_url.rstrip('/')}/api/v1/ingest/local-scans/requests/{request_id}"


def _retry_after(lease_expires_at: datetime | None, now: datetime) -> int:
    if lease_expires_at is None:
        return 30
    return max(1, min(300, round((lease_expires_at - now).total_seconds())))


__all__ = ["ingest_local_scan"]
