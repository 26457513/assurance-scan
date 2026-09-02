"""Durable, race-safe replay rejection for GitHub Actions OIDC JWTs."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.engine import AsyncEngine

from app.infrastructure.db.models import Base, GithubOidcReplay
from app.infrastructure.db.repositories.github_oidc_replays import (
    SqlAlchemyGithubOidcReplayRepository,
)
from app.modules.atomic.access.github_oidc import (
    GithubOidcClaims,
    OidcValidationError,
    consume_github_oidc_jti,
)


NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)


def _claims(*, jti: str = "f87d8b0c-29f8-4c11-8cc0-3eb13482b386") -> GithubOidcClaims:
    return GithubOidcClaims(
        subject="repo:owner/repo:ref:refs/heads/main",
        repository_id=424242,
        repository_owner_id=26457513,
        repository="owner/repo",
        run_id=123456789,
        run_number=26,
        run_attempt=1,
        sha="a" * 40,
        ref="refs/heads/main",
        event_name="push",
        actor="octocat",
        actor_id=583231,
        workflow_ref="owner/repo/.github/workflows/assurance-scan.yml@refs/heads/main",
        workflow_sha="a" * 40,
        issued_at=NOW - dt.timedelta(minutes=1),
        not_before=NOW - dt.timedelta(minutes=1),
        expires_at=NOW + dt.timedelta(minutes=9),
        jti=jti,
    )


async def _database(tmp_path) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'oidc-replay.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_concurrent_consumption_has_exactly_one_winner(tmp_path) -> None:
    engine, sessions = await _database(tmp_path)

    async def consume() -> str:
        async with sessions() as session:
            try:
                await consume_github_oidc_jti(
                    _claims(),
                    repository=SqlAlchemyGithubOidcReplayRepository(session),
                    now=NOW,
                )
            except OidcValidationError as exc:
                return exc.code
            return "consumed"

    outcomes = await asyncio.gather(consume(), consume())
    assert sorted(outcomes) == ["consumed", "oidc_replayed"]

    async with sessions() as session:
        replay = (await session.execute(select(GithubOidcReplay))).scalar_one()
        assert replay.jti_digest == hashlib.sha256(_claims().jti.encode()).digest()
        assert _claims().jti.encode() not in replay.jti_digest
        assert replay.github_repository_id == 424242
        assert replay.expires_at == (NOW + dt.timedelta(minutes=14)).replace(tzinfo=None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_replay_evidence_is_purgeable(tmp_path) -> None:
    engine, sessions = await _database(tmp_path)
    async with sessions() as session:
        repository = SqlAlchemyGithubOidcReplayRepository(session)
        await consume_github_oidc_jti(_claims(), repository=repository, now=NOW)
        assert await repository.purge_expired(now=NOW + dt.timedelta(minutes=15)) == 1
    async with sessions() as session:
        assert (await session.execute(select(GithubOidcReplay))).scalar_one_or_none() is None
    await engine.dispose()
