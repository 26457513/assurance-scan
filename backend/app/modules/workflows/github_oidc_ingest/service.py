"""Use-case sequencing for one authenticated GitHub Actions upload."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping, cast

from app.modules.atomic.ingestion.idempotency_guard import (
    ClaimDecision,
    GithubClaimCommand,
    acquire_github_claim,
    github_claim_handle,
)
from app.modules.atomic.ingestion.ingest_attempt import (
    IngestAttemptCommand,
    IngestAttemptRecord,
    build_ingest_attempt,
)
from app.modules.atomic.ingestion.usage_quota import (
    GithubQuotaCommand,
    GithubQuotaDecision,
    reserve_github_usage,
)
from app.modules.shared.contracts.ingest import GitHubIngestEnvelope, ResolvedProject
from app.modules.workflows.result_ingest import (
    build_v2_result_bundle,
    github_run_id,
    ingest_result_bundle,
)

from .models import (
    GithubIngestCommand,
    GithubIngestDependencies,
    GithubIngestError,
    GithubIngestOutcome,
    GithubIngestResult,
)


log = logging.getLogger(__name__)


async def ingest_github_result(
    command: GithubIngestCommand,
    dependencies: GithubIngestDependencies,
    *,
    now: datetime | None = None,
) -> GithubIngestResult:
    """Bind authenticated GitHub identity to one atomically persisted graph."""
    timestamp = now or datetime.now(timezone.utc)
    metadata = command.envelope.metadata
    producer = _mapping(metadata.get("producer"), "producer")
    repository = _mapping(metadata.get("repository"), "repository")
    source = _mapping(metadata.get("source"), "source")
    try:
        _validate_authenticated_identity(command, producer, repository)
    except GithubIngestError:
        await _record_attempt(
            command,
            dependencies,
            timestamp,
            outcome="rejected",
            reason_code="artifact_mismatch",
        )
        raise

    quota_result = await reserve_github_usage(
        GithubQuotaCommand(
            project_id=command.project_id,
            github_repository_id=command.github_repository_id,
            github_owner_id=command.github_owner_id,
            github_run_id=command.github_run_id,
            run_attempt=command.github_run_attempt,
            accepted_bytes=command.accepted_bytes,
            payload_hash=command.envelope.payload_hash,
            correlation_id=command.correlation_id,
        ),
        repository=dependencies.quotas,
        now=timestamp,
        limits=dependencies.github_usage_limits,
        shared_limits=dependencies.shared_usage_limits,
    )
    if not quota_result.allowed:
        capacity = quota_result.decision in {
            GithubQuotaDecision.REPOSITORY_INFLIGHT,
            GithubQuotaDecision.INSTANCE_INFLIGHT,
        }
        code = "capacity_exceeded" if capacity else "quota_exceeded"
        await _record_attempt(
            command,
            dependencies,
            timestamp,
            outcome="rejected",
            reason_code=code,
            retryable=True,
        )
        raise GithubIngestError(
            status=429,
            code=code,
            title="GitHub Actions upload capacity exceeded",
            detail="The upload cannot be accepted until capacity becomes available.",
            retryable=True,
            retry_after_seconds=quota_result.retry_after_seconds,
        )

    claim_command = GithubClaimCommand(
        github_repository_id=command.github_repository_id,
        github_owner_id=command.github_owner_id,
        github_run_id=command.github_run_id,
        run_attempt=command.github_run_attempt,
        project_id=command.project_id,
        payload_hash=command.envelope.payload_hash,
        accepted_bytes=command.accepted_bytes,
    )
    claim_result = await acquire_github_claim(
        claim_command,
        repository=dependencies.claims,
        now=timestamp,
    )
    if claim_result.decision is ClaimDecision.REPLAY:
        await _record_attempt(
            command,
            dependencies,
            timestamp,
            outcome="replayed",
            reason_code="idempotent_replay",
            run_id=claim_result.run_id,
        )
        return _result(command, GithubIngestOutcome.REPLAYED, claim_result.run_id)
    if claim_result.decision is ClaimDecision.IN_PROGRESS:
        await _record_attempt(
            command,
            dependencies,
            timestamp,
            outcome="replayed",
            reason_code="idempotent_replay",
            retryable=True,
        )
        return GithubIngestResult(
            outcome=GithubIngestOutcome.IN_PROGRESS,
            run_id=None,
            project_id=command.project_id,
            repository=command.repository,
            run_url=None,
            status="processing",
            status_url=_status_url(command),
            retry_after_seconds=_retry_after(claim_result.lease_expires_at, timestamp),
        )
    if claim_result.decision in {ClaimDecision.CONFLICT, ClaimDecision.TOMBSTONED}:
        await _record_attempt(
            command,
            dependencies,
            timestamp,
            outcome="rejected",
            reason_code="idempotency_conflict",
        )
        raise GithubIngestError(
            status=409,
            code="idempotency_conflict",
            title="GitHub run-attempt conflict",
            detail="This GitHub run attempt is already bound to different scan content.",
        )

    claim = github_claim_handle(claim_command, claim_result)
    dependencies.persistence.bind_claim(claim)
    run_id = github_run_id(
        command.github_repository_id,
        command.github_run_id,
        command.github_run_attempt,
    )
    dependencies.persistence.bind_attempt(
        _attempt(
            command,
            timestamp,
            outcome="accepted",
            reason_code="accepted",
            run_id=run_id,
        )
    )
    artifacts = {"findings": command.envelope.canonical_parts["findings"]}
    for name in ("sarif", "sbom"):
        content = command.envelope.canonical_parts.get(name)
        if content is not None:
            artifacts[name] = content
    result_bundle = build_v2_result_bundle(
        command.envelope.findings,
        command.envelope.source_contexts,
        artifacts,
    )
    run_number = int(producer["run_number"])
    run_attempt = command.github_run_attempt
    title = f"#{run_number} · assurance-scan"
    if run_attempt > 1:
        title += f" · attempt {run_attempt}"
    ingest_envelope = GitHubIngestEnvelope(
        project=ResolvedProject(
            project_id=command.project_id,
            repository=command.repository,
            github_repository_id=command.github_repository_id,
        ),
        github_run_id=command.github_run_id,
        checkout_sha=str(metadata["commit"]),
        head_sha=str(metadata["commit"]),
        git_object_format=cast(Any, metadata["git_object_format"]),
        branch=cast(str | None, metadata.get("branch")),
        conclusion="success",
        started_at=timestamp,
        completed_at=timestamp,
        run_number=run_number,
        run_attempt=run_attempt,
        run_url=(
            f"https://github.com/{command.repository}/actions/runs/{command.github_run_id}/attempts/{run_attempt}"
        ),
        event=str(producer["event_name"]),
        actor=str(producer["actor"]),
        display_title=title,
        payload_hash=command.envelope.payload_hash,
        source_content_hash=str(source["content_hash"]),
        source_manifest_version=str(source["manifest_version"]),
    )
    try:
        await ingest_result_bundle(
            dependencies.persistence,
            ingest_envelope,
            result_bundle,
            require_new=True,
        )
    except BaseException:
        try:
            await dependencies.claims.fail(claim, now=datetime.now(timezone.utc))
        except BaseException:
            log.error("GitHub ingest claim cleanup failed for correlation %s", command.correlation_id)
        try:
            await _record_attempt(
                command,
                dependencies,
                timestamp,
                outcome="failed_internal",
                reason_code="internal_persistence_failed",
                retryable=True,
            )
        except BaseException:
            log.error("GitHub ingest attempt cleanup failed for correlation %s", command.correlation_id)
        raise
    return _result(command, GithubIngestOutcome.CREATED, run_id)


async def _record_attempt(
    command: GithubIngestCommand,
    dependencies: GithubIngestDependencies,
    received_at: datetime,
    *,
    outcome: str,
    reason_code: str,
    retryable: bool = False,
    run_id: str | None = None,
) -> None:
    await dependencies.attempts.record(
        _attempt(
            command,
            received_at,
            outcome=outcome,
            reason_code=reason_code,
            retryable=retryable,
            run_id=run_id,
        )
    )


def _attempt(
    command: GithubIngestCommand,
    received_at: datetime,
    *,
    outcome: str,
    reason_code: str,
    retryable: bool = False,
    run_id: str | None = None,
) -> IngestAttemptRecord:
    completed_at = datetime.now(timezone.utc)
    if completed_at < received_at:
        completed_at = received_at
    return build_ingest_attempt(
        IngestAttemptCommand(
            correlation_id=command.correlation_id,
            origin="github",
            project_id=command.project_id,
            principal_kind="github_oidc",
            principal_reference=str(command.github_owner_id),
            canonical_request_key=(
                f"{command.github_repository_id}:{command.github_run_id}:{command.github_run_attempt}"
            ),
            outcome=outcome,
            reason_code=reason_code,
            retryable=retryable,
            wire_bytes=command.accepted_bytes,
            received_at=received_at,
            completed_at=completed_at,
            run_id=run_id,
        )
    )


def _validate_authenticated_identity(
    command: GithubIngestCommand,
    producer: Mapping[str, Any],
    repository: Mapping[str, Any],
) -> None:
    expected = (
        producer.get("kind") == "github-actions",
        producer.get("repository_id") == command.github_repository_id,
        producer.get("repository_owner_id") == command.github_owner_id,
        producer.get("run_id") == command.github_run_id,
        producer.get("run_attempt") == command.github_run_attempt,
        repository.get("provider") == "github",
        str(repository.get("full_name", "")).casefold() == command.repository.casefold(),
    )
    if not all(expected):
        raise GithubIngestError(
            status=409,
            code="artifact_mismatch",
            title="Authenticated identity does not match artifacts",
            detail="The uploaded metadata does not match the authenticated GitHub run.",
        )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GithubIngestError(
            status=422,
            code="schema_validation_failed",
            title="Invalid result metadata",
            detail=f"The validated {name} metadata is unavailable.",
        )
    return value


def _result(
    command: GithubIngestCommand,
    outcome: GithubIngestOutcome,
    run_id: str | None,
) -> GithubIngestResult:
    run_url = None if run_id is None else f"{command.public_base_url.rstrip('/')}/scans/{run_id}"
    return GithubIngestResult(
        outcome=outcome,
        run_id=run_id,
        project_id=command.project_id,
        repository=command.repository,
        run_url=run_url,
        status="completed",
    )


def _status_url(command: GithubIngestCommand) -> str:
    base = command.public_base_url.rstrip("/")
    return (
        f"{base}/api/v2/ingest/github-actions/requests/"
        f"{command.github_repository_id}/{command.github_run_id}/{command.github_run_attempt}"
    )


def _retry_after(lease_expires_at: datetime | None, now: datetime) -> int:
    if lease_expires_at is None:
        return 30
    return max(1, min(300, round((lease_expires_at - now).total_seconds())))


__all__ = ["ingest_github_result"]
