"""Focused tests for idempotency fencing, redaction, and usage quotas."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import ApiToken, Base, Project, Run, User
from app.infrastructure.db.repositories.ingest_requests import SqlAlchemyIdempotencyRepository
from app.infrastructure.db.repositories.ingest_usage import SqlAlchemyUsageQuotaRepository
from app.modules.atomic.ingestion.data_redactor import REDACTED, REDACTED_HOST, redact_json
from app.modules.atomic.ingestion.idempotency_guard import (
    ClaimCommand,
    ClaimDecision,
    acquire_claim,
    claim_handle,
    tombstone_completed_claim,
)
from app.modules.atomic.ingestion.usage_quota import (
    QuotaCommand,
    QuotaDecision,
    UsageSnapshot,
    decide_usage_quota,
)
from app.modules.shared.contracts.local_scan import UsageLimits


NOW = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
REQUEST_ID = "9af23e3e-0322-4d34-943f-45c42f020d66"
TOKEN_ID = "2a5cf164-85ea-40c3-a095-bf34eb829dd1"
HASH = "a" * 64
CANARY = "AS_CANARY_SECRET_DO_NOT_PERSIST_7f2b9c1e"


async def _database(path: Path) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        user = User(email="ingest@example.test", role="user")
        project = Project(tag="ingest", github_repo_key="owner/repo", github_repo="owner/repo")
        session.add_all([user, project])
        await session.flush()
        session.add(
            ApiToken(
                id=TOKEN_ID,
                user_id=user.id,
                label="laptop",
                label_key="laptop",
                selector="A" * 16,
                secret_digest=b"x" * 32,
                scope="scans:upload",
                token_version=1,
                created_at=NOW,
                expires_at=NOW + timedelta(days=30),
            )
        )
        await session.commit()
    return sessions


def _command(*, payload_hash: str = HASH, request_id: str = REQUEST_ID) -> ClaimCommand:
    return ClaimCommand(
        user_id=1,
        token_id=TOKEN_ID,
        client_request_id=request_id,
        project_id=1,
        payload_hash=payload_hash,
        accepted_bytes=1024,
    )


def _run(run_id: str) -> Run:
    return Run(
        run_id=run_id,
        project_id=1,
        origin="local",
        commit_sha="c" * 40,
        working_tree_dirty=False,
        source_content_hash="d" * 64,
        source_manifest_version="assurance-snapshot-v1",
        submitted_by_user_id=1,
        submitting_token_id=TOKEN_ID,
        payload_hash=HASH,
    )


async def test_concurrent_claim_has_one_owner_and_one_in_progress(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "claims.sqlite")

    async def claim() -> ClaimDecision:
        async with sessions() as session:
            result = await acquire_claim(_command(), repository=SqlAlchemyIdempotencyRepository(session), now=NOW)
            return result.decision

    decisions = await asyncio.gather(claim(), claim())
    assert sorted(decisions) == sorted([ClaimDecision.ACQUIRED, ClaimDecision.IN_PROGRESS])


async def test_conflict_takeover_retry_fencing_and_rollback(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "lifecycle.sqlite")
    async with sessions() as session:
        repository = SqlAlchemyIdempotencyRepository(session)
        acquired = await acquire_claim(_command(), repository=repository, now=NOW)
        old_handle = claim_handle(_command(), acquired)

    async with sessions() as session:
        conflict = await acquire_claim(
            _command(payload_hash="b" * 64),
            repository=SqlAlchemyIdempotencyRepository(session),
            now=NOW,
        )
        assert conflict.decision is ClaimDecision.CONFLICT

    later = NOW + timedelta(minutes=6)
    async with sessions() as session:
        repository = SqlAlchemyIdempotencyRepository(session)
        takeover = await acquire_claim(_command(), repository=repository, now=later)
        assert takeover.decision is ClaimDecision.STALE_TAKEOVER
        new_handle = claim_handle(_command(), takeover)
        assert not await repository.complete(old_handle, run_id="local-stale", now=later)
        await session.rollback()

        session.add(_run("local-new"))
        await session.flush()
        assert await repository.complete(new_handle, run_id="local-new", now=later)
        await session.rollback()

    async with sessions() as session:
        still_processing = await acquire_claim(
            _command(), repository=SqlAlchemyIdempotencyRepository(session), now=later
        )
        assert still_processing.decision is ClaimDecision.IN_PROGRESS
        assert still_processing.lease_id == new_handle.lease_id

    async with sessions() as session:
        repository = SqlAlchemyIdempotencyRepository(session)
        handle = claim_handle(
            _command(),
            await acquire_claim(_command(), repository=repository, now=later + timedelta(minutes=6)),
        )
        assert await repository.fail(handle, now=later + timedelta(minutes=6))

    async with sessions() as session:
        retry = await acquire_claim(
            _command(),
            repository=SqlAlchemyIdempotencyRepository(session),
            now=later + timedelta(minutes=7),
        )
        assert retry.decision is ClaimDecision.ACQUIRED


async def test_completed_replay_tombstone_and_expiry(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "tombstone.sqlite")
    async with sessions() as session:
        repository = SqlAlchemyIdempotencyRepository(session)
        acquired = await acquire_claim(_command(), repository=repository, now=NOW)
        session.add(_run("local-complete"))
        await session.flush()
        assert await repository.complete(claim_handle(_command(), acquired), run_id="local-complete", now=NOW)
        await session.commit()

    async with sessions() as session:
        repository = SqlAlchemyIdempotencyRepository(session)
        replay = await acquire_claim(_command(), repository=repository, now=NOW)
        assert replay.decision is ClaimDecision.REPLAY
        assert replay.run_id == "local-complete"
        assert await tombstone_completed_claim("local-complete", repository=repository, now=NOW)
        run = await session.get(Run, "local-complete")
        assert run is not None
        await session.delete(run)
        await session.commit()

    async with sessions() as session:
        repository = SqlAlchemyIdempotencyRepository(session)
        gone = await acquire_claim(_command(), repository=repository, now=NOW)
        assert gone.decision is ClaimDecision.TOMBSTONED
        assert await repository.purge_expired_tombstones(now=NOW + timedelta(days=31)) == 1
        fresh = await acquire_claim(_command(), repository=repository, now=NOW + timedelta(days=31))
        assert fresh.decision is ClaimDecision.ACQUIRED


def test_recursive_redaction_removes_canary_credentials_and_host_paths(caplog) -> None:
    source = {
        "findings": [
            {
                "message": f"leak {CANARY} at /Users/alice/private/repo/src/key.py",
                "token_id": TOKEN_ID,
                "secret": "actual-value",
            }
        ],
        "uri": "C:\\Users\\alice\\repo\\src\\key.py",
        "authorization": "Bearer very-secret-bearer-value",
        "nested": ["password=hunter2", "asu_v1_AAAAAAAAAAAAAAAA." + "B" * 43],
    }
    before = json.dumps(source)
    result = redact_json(source, repository_root="/Users/alice/private/repo")
    rendered = json.dumps(result.value)
    assert result.replacements >= 6
    assert CANARY not in rendered
    assert "hunter2" not in rendered
    assert "asu_v1_" not in rendered
    assert "/Users/alice" not in rendered
    assert "C:\\\\Users\\\\alice" not in rendered
    assert REDACTED in rendered
    assert REDACTED_HOST in rendered
    assert TOKEN_ID in rendered  # audit identifiers are not bearer secrets
    assert json.dumps(source) == before
    assert CANARY not in caplog.text


LIMITS = UsageLimits(
    uploads_per_token_hour=10,
    uploads_per_user_day=100,
    inflight_per_token=1,
    inflight_per_user=2,
    inflight_per_instance=4,
    retained_bytes_per_user=1000,
    retained_bytes_per_instance=5000,
    accepted_bytes_per_user_day=500,
)


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (UsageSnapshot(token_uploads_hour=10), QuotaDecision.TOKEN_HOURLY_RATE),
        (UsageSnapshot(user_uploads_day=100), QuotaDecision.USER_DAILY_RATE),
        (UsageSnapshot(token_inflight=1), QuotaDecision.TOKEN_INFLIGHT),
        (UsageSnapshot(user_inflight=2), QuotaDecision.USER_INFLIGHT),
        (UsageSnapshot(instance_inflight=4), QuotaDecision.INSTANCE_INFLIGHT),
        (UsageSnapshot(shared_instance_inflight=8), QuotaDecision.SHARED_INSTANCE_INFLIGHT),
        (UsageSnapshot(user_retained_bytes=901), QuotaDecision.USER_RETAINED_STORAGE),
        (UsageSnapshot(instance_retained_bytes=4901), QuotaDecision.INSTANCE_RETAINED_STORAGE),
        (UsageSnapshot(user_accepted_bytes_day=401), QuotaDecision.USER_DAILY_BYTES),
    ],
)
def test_quota_rejects_each_boundary(snapshot: UsageSnapshot, expected: QuotaDecision) -> None:
    command = QuotaCommand(1, TOKEN_ID, REQUEST_ID, accepted_bytes=100)
    assert decide_usage_quota(command, snapshot, limits=LIMITS) is expected


def test_quota_allows_exact_byte_boundaries_and_supports_kill_switch() -> None:
    exact = UsageSnapshot(
        user_retained_bytes=900,
        instance_retained_bytes=4900,
        user_accepted_bytes_day=400,
    )
    assert decide_usage_quota(QuotaCommand(1, TOKEN_ID, REQUEST_ID, 100), exact, limits=LIMITS) is QuotaDecision.ALLOWED
    assert (
        decide_usage_quota(
            QuotaCommand(1, TOKEN_ID, str(uuid.uuid4()), 0, enabled=False),
            UsageSnapshot(),
            limits=LIMITS,
        )
        is QuotaDecision.DISABLED
    )


async def test_sql_quota_lock_is_persisted_by_claim_and_enforces_inflight(
    tmp_path: Path,
) -> None:
    sessions = await _database(tmp_path / "quota.sqlite")
    first_command = QuotaCommand(1, TOKEN_ID, REQUEST_ID, accepted_bytes=100)
    async with sessions() as session:
        quota = SqlAlchemyUsageQuotaRepository(session)
        reservation = await quota.reserve(first_command, limits=LIMITS, now=NOW)
        assert reservation.allowed
        assert reservation.reservation is not None
        claimed = await acquire_claim(_command(), repository=SqlAlchemyIdempotencyRepository(session), now=NOW)
        assert claimed.decision is ClaimDecision.ACQUIRED

    second_id = "efcaa540-1a88-4df1-8eaa-c535fd31b130"
    async with sessions() as session:
        rejected = await SqlAlchemyUsageQuotaRepository(session).reserve(
            QuotaCommand(1, TOKEN_ID, second_id, accepted_bytes=100),
            limits=LIMITS,
            now=NOW,
        )
        assert rejected.decision is QuotaDecision.TOKEN_INFLIGHT
        assert rejected.retry_after_seconds == 30


async def test_sql_quota_release_rolls_back_reservation_lock(tmp_path: Path) -> None:
    sessions = await _database(tmp_path / "quota-release.sqlite")
    async with sessions() as session:
        repository = SqlAlchemyUsageQuotaRepository(session)
        result = await repository.reserve(
            QuotaCommand(1, TOKEN_ID, REQUEST_ID, accepted_bytes=100),
            limits=LIMITS,
            now=NOW,
        )
        assert result.reservation is not None
        assert await repository.release(result.reservation, now=NOW)
        assert not session.in_transaction()
