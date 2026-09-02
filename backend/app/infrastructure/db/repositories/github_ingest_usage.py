"""Serialized GitHub and shared push-ingest quota reservations."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.db.models import GithubIngestRequest, IngestRequest, IngestUsageCharge
from app.infrastructure.db.repositories.ingest_quota_lock import (
    QUOTA_LOCK_SESSION_KEY,
    acquire_global_ingest_quota_lock,
)
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
        _validate_binding(command.project_id, command.payload_hash, command.correlation_id)
        await acquire_global_ingest_quota_lock(self.session)
        existing = await self.session.scalar(
            select(GithubIngestRequest).where(
                GithubIngestRequest.github_repository_id == command.github_repository_id,
                GithubIngestRequest.github_run_id == command.github_run_id,
                GithubIngestRequest.run_attempt == command.run_attempt,
            )
        )
        if existing is not None and _github_no_work(existing, command, now=now):
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
        self.session.add(
            IngestUsageCharge(
                id=str(uuid.uuid4()),
                correlation_id=command.correlation_id,
                origin="github",
                accepted_bytes=command.accepted_bytes,
                github_repository_id=command.github_repository_id,
                github_owner_id=command.github_owner_id,
                charged_at=now,
                expires_at=now + dt.timedelta(days=2),
            )
        )
        await self.session.flush()
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

    async def _snapshot(
        self,
        command: GithubQuotaCommand,
        *,
        now: dt.datetime,
    ) -> GithubUsageSnapshot:
        hour_start = now - dt.timedelta(hours=1)
        day_start = now.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        repository_uploads = await self._charge_count(
            IngestUsageCharge.github_repository_id == command.github_repository_id,
            IngestUsageCharge.charged_at >= hour_start,
        )
        owner_uploads = await self._charge_count(
            IngestUsageCharge.github_owner_id == command.github_owner_id,
            IngestUsageCharge.charged_at >= day_start,
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
                select(func.coalesce(func.sum(IngestUsageCharge.accepted_bytes), 0)).where(
                    IngestUsageCharge.github_owner_id == command.github_owner_id,
                    IngestUsageCharge.charged_at >= day_start,
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

    async def _charge_count(self, *predicates: ColumnElement[bool]) -> int:
        return int(
            (
                await self.session.execute(select(func.count()).select_from(IngestUsageCharge).where(*predicates))
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


def _github_no_work(
    row: GithubIngestRequest,
    command: GithubQuotaCommand,
    *,
    now: dt.datetime,
) -> bool:
    tombstone_expiry = _aware(row.tombstone_expires_at)
    if row.state == "tombstoned":
        return tombstone_expiry is None or tombstone_expiry > now
    if (
        row.project_id != command.project_id
        or row.github_owner_id != command.github_owner_id
        or row.payload_hash != command.payload_hash
    ):
        return True
    lease_expiry = _aware(row.lease_expires_at)
    return row.state == "completed" or (row.state == "processing" and (lease_expiry is None or lease_expiry > now))


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value


def _validate_binding(project_id: int, payload_hash: str, correlation_id: str) -> None:
    if (
        project_id <= 0
        or len(payload_hash) != 64
        or any(character not in "0123456789abcdef" for character in payload_hash)
    ):
        raise ValueError("GitHub quota reservation requires a canonical project and payload hash")
    try:
        parsed = uuid.UUID(correlation_id)
    except ValueError as exc:
        raise ValueError("GitHub quota reservation requires a canonical correlation ID") from exc
    if str(parsed) != correlation_id:
        raise ValueError("GitHub quota reservation requires a canonical correlation ID")


__all__ = ["SqlAlchemyGithubUsageQuotaRepository"]
