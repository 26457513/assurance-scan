"""GitHub quota policy and minimized ingest-attempt retention tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import Base, IngestAttempt, Project
from app.infrastructure.db.repositories.ingest_attempts import SqlAlchemyIngestAttemptRepository
from app.modules.atomic.ingestion.ingest_attempt import IngestAttemptCommand, build_ingest_attempt
from app.modules.atomic.ingestion.usage_quota import (
    GithubQuotaCommand,
    GithubQuotaDecision,
    GithubUsageSnapshot,
    decide_github_usage_quota,
)
from app.modules.shared.contracts.ingest_v2 import GitHubUsageLimitsV2, SharedUsageLimitsV2


NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
LIMITS = GitHubUsageLimitsV2(
    uploads_per_repository_hour=3,
    uploads_per_owner_day=5,
    inflight_per_repository=2,
    accepted_bytes_per_owner_day=1000,
)
SHARED = SharedUsageLimitsV2(inflight_per_instance=4, inflight_local_per_instance=2)
COMMAND = GithubQuotaCommand(1, 424242, 26457513, 123456789, 1, 100)


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (GithubUsageSnapshot(repository_uploads_hour=3), GithubQuotaDecision.REPOSITORY_HOURLY_RATE),
        (GithubUsageSnapshot(owner_uploads_day=5), GithubQuotaDecision.OWNER_DAILY_RATE),
        (GithubUsageSnapshot(repository_inflight=2), GithubQuotaDecision.REPOSITORY_INFLIGHT),
        (GithubUsageSnapshot(instance_inflight=4), GithubQuotaDecision.INSTANCE_INFLIGHT),
        (GithubUsageSnapshot(owner_accepted_bytes_day=901), GithubQuotaDecision.OWNER_DAILY_BYTES),
    ],
)
def test_github_quota_rejects_every_frozen_boundary(
    snapshot: GithubUsageSnapshot,
    expected: GithubQuotaDecision,
) -> None:
    assert decide_github_usage_quota(COMMAND, snapshot, limits=LIMITS, shared_limits=SHARED) is expected


def test_github_quota_allows_exact_byte_boundary() -> None:
    assert (
        decide_github_usage_quota(
            COMMAND,
            GithubUsageSnapshot(owner_accepted_bytes_day=900),
            limits=LIMITS,
            shared_limits=SHARED,
        )
        is GithubQuotaDecision.ALLOWED
    )


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


async def test_attempt_hashes_raw_identity_and_expires_after_thirty_days(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "attempts.sqlite")
    correlation_id = str(uuid.uuid4())
    raw_principal = "26457513"
    raw_key = "424242:123456789:1"
    record = build_ingest_attempt(
        IngestAttemptCommand(
            correlation_id=correlation_id,
            origin="github",
            project_id=1,
            principal_kind="github_oidc",
            principal_reference=raw_principal,
            canonical_request_key=raw_key,
            outcome="rejected",
            reason_code="quota_exceeded",
            retryable=True,
            wire_bytes=123,
            received_at=NOW,
            completed_at=NOW,
        )
    )
    assert record.expires_at == NOW + timedelta(days=30)
    assert raw_principal not in record.principal_reference_hash
    assert raw_key not in record.canonical_request_key_hash

    async with sessions() as session:
        repository = SqlAlchemyIngestAttemptRepository(session)
        await repository.record(record)
        row = (await session.execute(select(IngestAttempt))).scalar_one()
        assert row.correlation_id == correlation_id
        assert await repository.purge_expired(now=NOW + timedelta(days=29)) == 0
        assert await repository.purge_expired(now=NOW + timedelta(days=30)) == 1
