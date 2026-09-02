"""Use-case sequencing for one authenticated GitHub Actions upload."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, cast

from app.modules.atomic.ingestion.idempotency_guard import (
    ClaimDecision,
    GithubClaimCommand,
    acquire_github_claim,
    github_claim_handle,
)
from app.modules.shared.contracts.ingest import GitHubIngestEnvelope, ResolvedProject
from app.modules.workflows.result_ingest import build_v2_result_bundle, ingest_result_bundle

from .models import (
    GithubIngestCommand,
    GithubIngestDependencies,
    GithubIngestError,
    GithubIngestOutcome,
    GithubIngestResult,
)


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
    _validate_authenticated_identity(command, producer, repository)

    claim_command = GithubClaimCommand(
        github_repository_id=command.github_repository_id,
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
        return _result(command, GithubIngestOutcome.REPLAYED, claim_result.run_id)
    if claim_result.decision is ClaimDecision.IN_PROGRESS:
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
        raise GithubIngestError(
            status=409,
            code="idempotency_conflict",
            title="GitHub run-attempt conflict",
            detail="This GitHub run attempt is already bound to different scan content.",
        )

    claim = github_claim_handle(claim_command, claim_result)
    dependencies.persistence.bind_claim(claim)
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
            f"https://github.com/{command.repository}/actions/runs/"
            f"{command.github_run_id}/attempts/{run_attempt}"
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
        await dependencies.claims.fail(claim, now=datetime.now(timezone.utc))
        raise
    run_id = (
        f"gh-{command.github_repository_id}-{command.github_run_id}-"
        f"{command.github_run_attempt}"
    )
    return _result(command, GithubIngestOutcome.CREATED, run_id)


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
