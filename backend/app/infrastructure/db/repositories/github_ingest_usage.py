"""Serialized GitHub and shared push-ingest quota reservations."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.db.models import GithubIngestRequest, IngestRequest, Project
from app.infrastructure.db.repositories.ingest_quota_lock import QUOTA_LOCK_SESSION_KEY
from app.modules.atomic.ingestion.usage_quota import (
    GithubQuotaCommand,
    GithubQuotaDecision,
    GithubQuotaResult,
    GithubUsageReservation,
    GithubUsageSnapshot,
    decide_github_usage_quota,
)
from app.modules.shared.contracts.ingest_v2 import GitHubUsageLimitsV2, SharedUsageLimitsV2


class SqlAlchemyGithubUsageQuotaRepository:
    """Hold a write lock until the matching idempotency claim is committed."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve(
        self,
        command: GithubQuotaCommand,
        *,
        limits: GitHubUsageLimitsV2,
        shared_limits: SharedUsageLimitsV2,
        now: dt.datetime,
    ) -> GithubQuotaResult:
        await self._begin_write(command.project_id)
        self.session.info[QUOTA_LOCK_SESSION_KEY] = True
        existing = await self.session.scalar(
            select(GithubIngestRequest.id).where(
                GithubIngestRequest.github_repository_id == command.github_repository_id,
                GithubIngestRequest.github_run_id == command.github_run_id,
                GithubIngestRequest.run_attempt == command.run_attempt,
            )
        )
        if existing is not None:
            return self._allowed(command, now)
        snapshot = await self._snapshot(command, now=now)
        decision = decide_github_usage_quota(
            command,
            snapshot,
            limits=limits,
            shared_limits=shared_limits,
        )
        if decision is not GithubQuotaDecision.ALLOWED:
            await self.session.rollback()
            self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
            return GithubQuotaResult(decision, retry_after_seconds=_retry_after(decision))
        return self._allowed(command, now)

    async def release(
        self,
        reservation: GithubUsageReservation,
        *,
        now: dt.datetime,
    ) -> bool:
        del reservation, now
        had_transaction = self.session.in_transaction()
        await self.session.rollback()
        self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
        return had_transaction

    async def _begin_write(self, project_id: int) -> None:
        if self.session.in_transaction():
            raise RuntimeError("GitHub quota reservation requires a clean session")
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))
            return
        await self.session.execute(select(Project.id).where(Project.id == project_id).with_for_update())

    async def _snapshot(
        self,
        command: GithubQuotaCommand,
        *,
        now: dt.datetime,
    ) -> GithubUsageSnapshot:
        hour_start = now - dt.timedelta(hours=1)
        day_start = now.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        repository_uploads = await self._count(
            GithubIngestRequest.github_repository_id == command.github_repository_id,
            GithubIngestRequest.created_at >= hour_start,
        )
        owner_uploads = await self._count(
            GithubIngestRequest.github_owner_id == command.github_owner_id,
            GithubIngestRequest.created_at >= day_start,
        )
        repository_inflight = await self._count(
            GithubIngestRequest.github_repository_id == command.github_repository_id,
            GithubIngestRequest.state == "processing",
            GithubIngestRequest.lease_expires_at > now,
        )
        github_inflight = await self._count(
            GithubIngestRequest.state == "processing",
            GithubIngestRequest.lease_expires_at > now,
        )
        local_inflight = int(
            await self.session.scalar(
                select(func.count())
                .select_from(IngestRequest)
                .where(
                    IngestRequest.state == "processing",
                    IngestRequest.lease_expires_at > now,
                )
            )
            or 0
        )
        owner_bytes = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(GithubIngestRequest.accepted_bytes), 0)).where(
                    GithubIngestRequest.github_owner_id == command.github_owner_id,
                    GithubIngestRequest.created_at >= day_start,
                )
            )
            or 0
        )
        return GithubUsageSnapshot(
            repository_uploads_hour=repository_uploads,
            owner_uploads_day=owner_uploads,
            repository_inflight=repository_inflight,
            instance_inflight=github_inflight + local_inflight,
            owner_accepted_bytes_day=owner_bytes,
        )

    async def _count(self, *predicates: ColumnElement[bool]) -> int:
        return int(
            (
                await self.session.execute(select(func.count()).select_from(GithubIngestRequest).where(*predicates))
            ).scalar_one()
        )

    @staticmethod
    def _allowed(command: GithubQuotaCommand, now: dt.datetime) -> GithubQuotaResult:
        return GithubQuotaResult(
            GithubQuotaDecision.ALLOWED,
            GithubUsageReservation(
                github_repository_id=command.github_repository_id,
                github_owner_id=command.github_owner_id,
                github_run_id=command.github_run_id,
                run_attempt=command.run_attempt,
                accepted_bytes=command.accepted_bytes,
                reserved_at=now,
            ),
        )


def _retry_after(decision: GithubQuotaDecision) -> int:
    if decision is GithubQuotaDecision.REPOSITORY_HOURLY_RATE:
        return 3600
    if decision in {
        GithubQuotaDecision.OWNER_DAILY_RATE,
        GithubQuotaDecision.OWNER_DAILY_BYTES,
    }:
        return 86_400
    return 30


__all__ = ["SqlAlchemyGithubUsageQuotaRepository"]
