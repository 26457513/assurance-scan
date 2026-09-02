"""GitHub run-attempt fencing and shared result-persistence integration."""

from __future__ import annotations

import asyncio
import logging
import uuid
from unittest.mock import AsyncMock
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import (
    Base,
    Finding,
    GithubIngestRequest,
    IngestAttempt,
    IngestUsageCharge,
    Project,
    Run,
)
from app.infrastructure.db.repositories.github_ingest_requests import (
    SqlAlchemyGithubIdempotencyRepository,
)
from app.infrastructure.db.repositories.github_ingest_usage import (
    SqlAlchemyGithubUsageQuotaRepository,
)
from app.infrastructure.db.repositories.ingest_attempts import SqlAlchemyIngestAttemptRepository
from app.infrastructure.github_oidc_ingest import (
    GithubClaimCompletingSqlAlchemyPersistence,
)
from app.infrastructure.db.retention import prepare_runs_for_deletion, run_retention_cleanup
from app.infrastructure.ingest_v2_contract import CheckedInEnvelopeSchemaValidator
from app.modules.atomic.ingestion.idempotency_guard import (
    ClaimDecision,
    GithubClaimCommand,
    acquire_github_claim,
    github_claim_handle,
)
from app.modules.atomic.ingestion.usage_quota import GithubQuotaCommand
from app.modules.workflows.github_oidc_ingest import (
    GithubIngestCommand,
    GithubIngestDependencies,
    GithubIngestError,
    GithubIngestOutcome,
    ingest_github_result,
)
from app.modules.workflows.result_ingest_v2_contract import build_validated_envelope_v2
from app.modules.shared.contracts.ingest_v2 import (
    GITHUB_USAGE_LIMITS_V2,
    SHARED_USAGE_LIMITS_V2,
    GitHubUsageLimitsV2,
    SharedUsageLimitsV2,
)


NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
HASH = "a" * 64
FIXTURES = Path(__file__).resolve().parents[2] / "resources" / "fixtures" / "ingest-v2"


def _correlation() -> str:
    return str(uuid.uuid4())


def _dependencies(
    session: AsyncSession,
    *,
    failing: bool = False,
) -> GithubIngestDependencies:
    claims = SqlAlchemyGithubIdempotencyRepository(session)
    persistence_type = _FailingPersistence if failing else GithubClaimCompletingSqlAlchemyPersistence
    return GithubIngestDependencies(
        claims=claims,
        quotas=SqlAlchemyGithubUsageQuotaRepository(session),
        attempts=SqlAlchemyIngestAttemptRepository(session),
        persistence=persistence_type(session, claims),
    )


class _FailingPersistence(GithubClaimCompletingSqlAlchemyPersistence):
    async def insert_findings(self, findings: object) -> None:
        raise RuntimeError("injected persistence failure")


async def _database(path: Path) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add(
            Project(
                tag="github-424242",
                github_repo="26457513/assurance-scan",
                github_repo_key="26457513/assurance-scan",
                github_repository_id=424242,
            )
        )
        await session.commit()
    return sessions


def _claim(*, payload_hash: str = HASH) -> GithubClaimCommand:
    return GithubClaimCommand(
        github_repository_id=424242,
        github_owner_id=26457513,
        github_run_id=123456789,
        run_attempt=1,
        project_id=1,
        payload_hash=payload_hash,
        accepted_bytes=1024,
    )


async def test_concurrent_github_claim_has_one_owner(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "concurrent.sqlite")

    async def acquire() -> ClaimDecision:
        async with sessions() as session:
            result = await acquire_github_claim(
                _claim(),
                repository=SqlAlchemyGithubIdempotencyRepository(session),
                now=NOW,
            )
            return result.decision

    decisions = await asyncio.gather(acquire(), acquire())
    assert sorted(decisions) == sorted([ClaimDecision.ACQUIRED, ClaimDecision.IN_PROGRESS])


async def test_github_active_duplicate_is_replayed_without_second_charge(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "active-replay.sqlite")
    envelope = build_validated_envelope_v2(
        {
            "metadata": (FIXTURES / "github-metadata.json").read_bytes(),
            "findings": (FIXTURES / "findings.json").read_bytes(),
            "source_contexts": (FIXTURES / "source-contexts.json").read_bytes(),
            "sarif": b'{"version":"2.1.0","runs":[]}',
        },
        schema_validator=CheckedInEnvelopeSchemaValidator(),
    )
    command = GithubIngestCommand(
        1,
        "26457513/assurance-scan",
        424242,
        26457513,
        123456789,
        1,
        1024,
        correlation_id=_correlation(),
        envelope=envelope,
        public_base_url="https://scan.example.test",
    )
    async with sessions() as session:
        quota = await SqlAlchemyGithubUsageQuotaRepository(session).reserve(
            GithubQuotaCommand(
                project_id=1,
                github_repository_id=424242,
                github_owner_id=26457513,
                github_run_id=123456789,
                run_attempt=1,
                accepted_bytes=1024,
                payload_hash=envelope.payload_hash,
                correlation_id=command.correlation_id,
            ),
            limits=GITHUB_USAGE_LIMITS_V2,
            shared_limits=SHARED_USAGE_LIMITS_V2,
            now=NOW,
        )
        assert quota.allowed
        claim = await acquire_github_claim(
            GithubClaimCommand(
                424242,
                26457513,
                123456789,
                1,
                1,
                envelope.payload_hash,
                1024,
            ),
            repository=SqlAlchemyGithubIdempotencyRepository(session),
            now=NOW,
        )
        assert claim.acquired

        replay_command = replace(command, correlation_id=_correlation())
        result = await ingest_github_result(replay_command, _dependencies(session), now=NOW)
        assert result.outcome is GithubIngestOutcome.IN_PROGRESS
        assert result.run_id is None
        assert result.status_url is not None
        assert result.retry_after_seconds is not None
        attempt = (await session.execute(select(IngestAttempt))).scalar_one()
        assert attempt.outcome == "replayed"
        assert attempt.reason_code == "idempotent_replay"
        assert attempt.retryable is True
        assert attempt.correlation_id == replay_command.correlation_id
        assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 1


async def test_github_claim_conflict_failure_and_stale_fencing(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "lifecycle.sqlite")
    async with sessions() as session:
        repository = SqlAlchemyGithubIdempotencyRepository(session)
        acquired = await acquire_github_claim(_claim(), repository=repository, now=NOW)
        stale_handle = github_claim_handle(_claim(), acquired)

    async with sessions() as session:
        conflict = await acquire_github_claim(
            _claim(payload_hash="b" * 64),
            repository=SqlAlchemyGithubIdempotencyRepository(session),
            now=NOW,
        )
        assert conflict.decision is ClaimDecision.CONFLICT

    later = NOW + timedelta(minutes=6)
    async with sessions() as session:
        repository = SqlAlchemyGithubIdempotencyRepository(session)
        takeover = await acquire_github_claim(_claim(), repository=repository, now=later)
        assert takeover.decision is ClaimDecision.STALE_TAKEOVER
        assert not await repository.fail(stale_handle, now=later)
        assert await repository.fail(github_claim_handle(_claim(), takeover), now=later)

    async with sessions() as session:
        retry = await acquire_github_claim(
            _claim(),
            repository=SqlAlchemyGithubIdempotencyRepository(session),
            now=later,
        )
        assert retry.decision is ClaimDecision.ACQUIRED


async def test_github_workflow_persists_once_and_replays(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "workflow.sqlite")
    raw_parts = {
        "metadata": (FIXTURES / "github-metadata.json").read_bytes(),
        "findings": (FIXTURES / "findings.json").read_bytes(),
        "source_contexts": (FIXTURES / "source-contexts.json").read_bytes(),
        "sarif": b'{"version":"2.1.0","runs":[]}',
    }
    envelope = build_validated_envelope_v2(
        raw_parts,
        schema_validator=CheckedInEnvelopeSchemaValidator(),
    )
    command = GithubIngestCommand(
        project_id=1,
        repository="26457513/assurance-scan",
        github_repository_id=424242,
        github_owner_id=26457513,
        github_run_id=123456789,
        github_run_attempt=1,
        accepted_bytes=sum(map(len, raw_parts.values())),
        envelope=envelope,
        public_base_url="https://scan.example.test",
        correlation_id=_correlation(),
    )

    async with sessions() as session:
        result = await ingest_github_result(
            command,
            _dependencies(session),
            now=NOW,
        )
        assert result.outcome is GithubIngestOutcome.CREATED
        assert result.run_id == "gh-424242-123456789-1"

    async with sessions() as session:
        replay = await ingest_github_result(
            replace(command, correlation_id=_correlation()),
            _dependencies(session),
            now=NOW,
        )
        assert replay.outcome is GithubIngestOutcome.REPLAYED
        assert replay.run_id == result.run_id
        assert await session.scalar(select(func.count()).select_from(Run)) == 1
        assert await session.scalar(select(func.count()).select_from(Finding)) == len(envelope.findings["findings"])
        claim = (await session.execute(select(GithubIngestRequest))).scalar_one()
        assert claim.state == "completed"
        assert claim.run_id == result.run_id
        attempts = (await session.execute(select(IngestAttempt))).scalars().all()
        assert [attempt.outcome for attempt in attempts] == ["accepted", "replayed"]
        assert all("26457513" not in attempt.principal_reference_hash for attempt in attempts)
        assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 1

    conflicting = replace(
        command,
        envelope=replace(envelope, payload_hash="b" * 64),
        correlation_id=_correlation(),
    )
    async with sessions() as session:
        with pytest.raises(GithubIngestError) as raised:
            await ingest_github_result(
                conflicting,
                _dependencies(session),
                now=NOW,
            )
        assert raised.value.status == 409
        assert raised.value.code == "idempotency_conflict"
        attempts = (await session.execute(select(IngestAttempt).order_by(IngestAttempt.received_at))).scalars().all()
        assert [attempt.outcome for attempt in attempts] == ["accepted", "replayed", "rejected"]
        assert attempts[-1].reason_code == "idempotency_conflict"
        assert attempts[-1].correlation_id == conflicting.correlation_id
        assert attempts[-1].retryable is False
        assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 1


async def test_github_workflow_rejects_artifact_identity_mismatch(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "identity.sqlite")
    envelope = build_validated_envelope_v2(
        {
            "metadata": (FIXTURES / "github-metadata.json").read_bytes(),
            "findings": (FIXTURES / "findings.json").read_bytes(),
            "source_contexts": (FIXTURES / "source-contexts.json").read_bytes(),
            "sarif": b'{"version":"2.1.0","runs":[]}',
        },
        schema_validator=CheckedInEnvelopeSchemaValidator(),
    )
    command = GithubIngestCommand(
        1,
        "other/repository",
        424242,
        26457513,
        123456789,
        1,
        1024,
        correlation_id=_correlation(),
        envelope=envelope,
    )
    async with sessions() as session:
        with pytest.raises(GithubIngestError) as raised:
            await ingest_github_result(
                command,
                _dependencies(session),
                now=NOW,
            )
        assert raised.value.code == "artifact_mismatch"
        assert await session.scalar(select(func.count()).select_from(GithubIngestRequest)) == 0
        attempt = (await session.execute(select(IngestAttempt))).scalar_one()
        assert attempt.origin == "github"
        assert attempt.outcome == "rejected"
        assert attempt.reason_code == "artifact_mismatch"
        assert attempt.retryable is False
        assert attempt.correlation_id == command.correlation_id
        assert attempt.run_id is None
        assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 0


@pytest.mark.parametrize(
    ("limits", "shared_limits", "reason_code"),
    [
        (GitHubUsageLimitsV2(uploads_per_repository_hour=0), SharedUsageLimitsV2(), "quota_exceeded"),
        (GitHubUsageLimitsV2(uploads_per_owner_day=0), SharedUsageLimitsV2(), "quota_exceeded"),
        (GitHubUsageLimitsV2(inflight_per_repository=0), SharedUsageLimitsV2(), "capacity_exceeded"),
        (GitHubUsageLimitsV2(), SharedUsageLimitsV2(inflight_per_instance=0), "capacity_exceeded"),
    ],
)
async def test_github_workflow_quota_rejections_create_safe_attempt_only(
    tmp_path: Path,
    limits: GitHubUsageLimitsV2,
    shared_limits: SharedUsageLimitsV2,
    reason_code: str,
) -> None:
    sessions = await _database(tmp_path / f"quota-{uuid.uuid4()}.sqlite")
    envelope = build_validated_envelope_v2(
        {
            "metadata": (FIXTURES / "github-metadata.json").read_bytes(),
            "findings": (FIXTURES / "findings.json").read_bytes(),
            "source_contexts": (FIXTURES / "source-contexts.json").read_bytes(),
            "sarif": b'{"version":"2.1.0","runs":[]}',
        },
        schema_validator=CheckedInEnvelopeSchemaValidator(),
    )
    command = GithubIngestCommand(
        1,
        "26457513/assurance-scan",
        424242,
        26457513,
        123456789,
        1,
        1024,
        correlation_id=_correlation(),
        envelope=envelope,
    )
    async with sessions() as session:
        dependencies = replace(
            _dependencies(session),
            github_usage_limits=limits,
            shared_usage_limits=shared_limits,
        )
        with pytest.raises(GithubIngestError) as raised:
            await ingest_github_result(command, dependencies, now=NOW)
        assert raised.value.status == 429
        assert raised.value.code == reason_code
        attempt = (await session.execute(select(IngestAttempt))).scalar_one()
        assert attempt.outcome == "rejected"
        assert attempt.reason_code == reason_code
        assert attempt.retryable is True
        assert attempt.correlation_id == command.correlation_id
        assert await session.scalar(select(func.count()).select_from(GithubIngestRequest)) == 0
        assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 0


async def test_github_workflow_rolls_back_graph_and_releases_failed_claim(
    tmp_path: Path,
) -> None:
    sessions = await _database(tmp_path / "rollback.sqlite")
    envelope = build_validated_envelope_v2(
        {
            "metadata": (FIXTURES / "github-metadata.json").read_bytes(),
            "findings": (FIXTURES / "findings.json").read_bytes(),
            "source_contexts": (FIXTURES / "source-contexts.json").read_bytes(),
            "sarif": b'{"version":"2.1.0","runs":[]}',
        },
        schema_validator=CheckedInEnvelopeSchemaValidator(),
    )
    command = GithubIngestCommand(
        1,
        "26457513/assurance-scan",
        424242,
        26457513,
        123456789,
        1,
        1024,
        correlation_id=_correlation(),
        envelope=envelope,
    )
    async with sessions() as session:
        with pytest.raises(RuntimeError, match="injected persistence failure"):
            await ingest_github_result(
                command,
                _dependencies(session, failing=True),
                now=NOW,
            )

    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Run)) == 0
        claim = (await session.execute(select(GithubIngestRequest))).scalar_one()
        assert claim.state == "failed"
        attempts = (await session.execute(select(IngestAttempt))).scalars().all()
        assert [attempt.outcome for attempt in attempts] == ["failed_internal"]
        assert attempts[0].reason_code == "internal_persistence_failed"
        assert attempts[0].retryable is True
        assert attempts[0].correlation_id == command.correlation_id
        assert attempts[0].run_id is None
        assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 1
        await session.rollback()
        retry = await ingest_github_result(
            replace(command, correlation_id=_correlation()),
            _dependencies(session),
            now=NOW,
        )
        assert retry.outcome is GithubIngestOutcome.CREATED
        assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 2


async def test_github_cleanup_failures_do_not_mask_primary_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sessions = await _database(tmp_path / "cleanup-failure.sqlite")
    envelope = build_validated_envelope_v2(
        {
            "metadata": (FIXTURES / "github-metadata.json").read_bytes(),
            "findings": (FIXTURES / "findings.json").read_bytes(),
            "source_contexts": (FIXTURES / "source-contexts.json").read_bytes(),
            "sarif": b'{"version":"2.1.0","runs":[]}',
        },
        schema_validator=CheckedInEnvelopeSchemaValidator(),
    )
    command = GithubIngestCommand(
        1,
        "26457513/assurance-scan",
        424242,
        26457513,
        123456789,
        1,
        1024,
        correlation_id=_correlation(),
        envelope=envelope,
    )
    async with sessions() as session:
        dependencies = _dependencies(session, failing=True)
        fail_claim = AsyncMock(side_effect=RuntimeError("claim cleanup secret"))
        fail_attempt = AsyncMock(side_effect=RuntimeError("attempt cleanup secret"))
        monkeypatch.setattr(dependencies.claims, "fail", fail_claim)
        monkeypatch.setattr(dependencies.attempts, "record", fail_attempt)
        caplog.set_level(logging.ERROR, logger="app.modules.workflows.github_oidc_ingest.service")

        with pytest.raises(RuntimeError, match="injected persistence failure"):
            await ingest_github_result(command, dependencies, now=NOW)

        fail_claim.assert_awaited_once()
        fail_attempt.assert_awaited_once()
        assert command.correlation_id in caplog.text
        assert "claim cleanup secret" not in caplog.text
        assert "attempt cleanup secret" not in caplog.text


async def test_github_run_deletion_tombstones_and_expires_claim(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "retention.sqlite")
    raw_parts = {
        "metadata": (FIXTURES / "github-metadata.json").read_bytes(),
        "findings": (FIXTURES / "findings.json").read_bytes(),
        "source_contexts": (FIXTURES / "source-contexts.json").read_bytes(),
        "sarif": b'{"version":"2.1.0","runs":[]}',
    }
    envelope = build_validated_envelope_v2(
        raw_parts,
        schema_validator=CheckedInEnvelopeSchemaValidator(),
    )
    command = GithubIngestCommand(
        project_id=1,
        repository="26457513/assurance-scan",
        github_repository_id=424242,
        github_owner_id=26457513,
        github_run_id=123456789,
        github_run_attempt=1,
        accepted_bytes=sum(map(len, raw_parts.values())),
        correlation_id=_correlation(),
        envelope=envelope,
    )
    async with sessions() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))
        await session.commit()
        created = await ingest_github_result(command, _dependencies(session), now=NOW)
        assert created.run_id is not None
        assert await prepare_runs_for_deletion(session, [created.run_id], now=NOW) == 1
        await session.execute(delete(Run).where(Run.run_id == created.run_id))
        await session.commit()
        claim = (await session.execute(select(GithubIngestRequest))).scalar_one()
        assert claim.state == "tombstoned"
        assert claim.run_id is None
        await session.rollback()
        tombstone_retry = replace(command, correlation_id=_correlation())
        with pytest.raises(GithubIngestError) as raised:
            await ingest_github_result(tombstone_retry, _dependencies(session), now=NOW)
        assert raised.value.status == 409
        assert raised.value.code == "idempotency_conflict"
        attempts = (await session.execute(select(IngestAttempt).order_by(IngestAttempt.received_at))).scalars().all()
        assert [attempt.outcome for attempt in attempts] == ["accepted", "rejected"]
        assert attempts[-1].reason_code == "idempotency_conflict"
        assert attempts[-1].correlation_id == tombstone_retry.correlation_id
        assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 1
        cleanup = await run_retention_cleanup(session, now=NOW + timedelta(days=31))
        assert cleanup.tombstones == 1
        assert await session.scalar(select(func.count()).select_from(GithubIngestRequest)) == 0
