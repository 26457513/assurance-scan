"""Serialized SQLAlchemy usage-quota adapter for local ingestion."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.db.models import (
    GithubIngestRequest,
    IngestRequest,
    IngestUsageCharge,
    Run,
    ScannerArtifact,
    ScannerRun,
)
from app.infrastructure.db.repositories.ingest_quota_lock import (
    QUOTA_LOCK_SESSION_KEY,
    acquire_global_ingest_quota_lock,
)
from app.modules.atomic.ingestion.usage_quota import (
    QuotaCommand,
    QuotaDecision,
    QuotaResult,
    UsageReservation,
    UsageSnapshot,
    decide_usage_quota,
)
from app.modules.shared.contracts.local_scan import UsageLimits
from app.modules.shared.contracts.ingest_v2 import SharedUsageLimitsV2


class SqlAlchemyUsageQuotaRepository:
    """Hold a database write lock from policy check through claim insertion.

    An allowed result intentionally leaves the transaction open.  The caller
    must acquire its idempotency claim with the same session, which persists the
    reservation by committing the claim.  ``release`` rolls the open
    transaction back when ingestion stops before claim creation.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve(
        self,
        command: QuotaCommand,
        *,
        limits: UsageLimits,
        shared_limits: SharedUsageLimitsV2,
        now: dt.datetime,
    ) -> QuotaResult:
        _validate_binding(command.project_id, command.payload_hash, command.correlation_id)
        await acquire_global_ingest_quota_lock(self.session)
        existing = (
            await self.session.execute(
                select(IngestRequest).where(
                    IngestRequest.submitted_by_user_id == command.user_id,
                    IngestRequest.client_request_id == command.client_request_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None and _local_no_work(existing, command, now=now):
            return self._allowed(command, now)
        snapshot = await self._snapshot(command, now=now)
        decision = decide_usage_quota(
            command,
            snapshot,
            limits=limits,
            shared_limits=shared_limits,
        )
        if decision is not QuotaDecision.ALLOWED:
            await self.session.rollback()
            self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
            return QuotaResult(decision, retry_after_seconds=_retry_after(decision))
        self.session.add(
            IngestUsageCharge(
                id=str(uuid.uuid4()),
                correlation_id=command.correlation_id,
                origin="local",
                accepted_bytes=command.accepted_bytes,
                local_user_id=command.user_id,
                local_token_id=command.token_id,
                charged_at=now,
                expires_at=now + dt.timedelta(days=2),
            )
        )
        await self.session.flush()
        return self._allowed(command, now)

    @staticmethod
    def _allowed(command: QuotaCommand, now: dt.datetime) -> QuotaResult:
        return QuotaResult(
            QuotaDecision.ALLOWED,
            UsageReservation(
                user_id=command.user_id,
                token_id=command.token_id,
                client_request_id=command.client_request_id,
                accepted_bytes=command.accepted_bytes,
                reserved_at=now,
            ),
        )

    async def release(self, reservation: UsageReservation, *, now: dt.datetime) -> bool:
        del reservation, now
        had_transaction = self.session.in_transaction()
        await self.session.rollback()
        self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
        return had_transaction

    async def _snapshot(self, command: QuotaCommand, *, now: dt.datetime) -> UsageSnapshot:
        hour_start = now - dt.timedelta(hours=1)
        day_start = now.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        token_uploads = await self._charge_count(
            IngestUsageCharge.local_token_id == command.token_id,
            IngestUsageCharge.charged_at >= hour_start,
        )
        user_uploads = await self._charge_count(
            IngestUsageCharge.local_user_id == command.user_id,
            IngestUsageCharge.charged_at >= day_start,
        )
        token_inflight = await self._claim_count(
            IngestRequest.submitting_token_id == command.token_id,
            IngestRequest.state == "processing",
            IngestRequest.lease_expires_at > now,
        )
        user_inflight = await self._claim_count(
            IngestRequest.submitted_by_user_id == command.user_id,
            IngestRequest.state == "processing",
            IngestRequest.lease_expires_at > now,
        )
        local_instance_inflight = await self._claim_count(
            IngestRequest.state == "processing", IngestRequest.lease_expires_at > now
        )
        github_instance_inflight = int(
            (
                await self.session.execute(
                    select(func.count())
                    .select_from(GithubIngestRequest)
                    .where(
                        GithubIngestRequest.state == "processing",
                        GithubIngestRequest.lease_expires_at > now,
                    )
                )
            ).scalar_one()
        )
        user_retained = await self._retained_bytes(user_id=command.user_id)
        instance_retained = await self._retained_bytes()
        user_pending = await self._accepted_bytes(
            IngestRequest.submitted_by_user_id == command.user_id,
            IngestRequest.state == "processing",
            IngestRequest.lease_expires_at > now,
        )
        instance_pending = await self._accepted_bytes(
            IngestRequest.state == "processing", IngestRequest.lease_expires_at > now
        )
        user_daily_bytes = await self._charged_bytes(
            IngestUsageCharge.local_user_id == command.user_id,
            IngestUsageCharge.charged_at >= day_start,
        )
        return UsageSnapshot(
            token_uploads_hour=token_uploads,
            user_uploads_day=user_uploads,
            token_inflight=token_inflight,
            user_inflight=user_inflight,
            instance_inflight=local_instance_inflight,
            shared_instance_inflight=local_instance_inflight + github_instance_inflight,
            user_retained_bytes=user_retained + user_pending,
            instance_retained_bytes=instance_retained + instance_pending,
            user_accepted_bytes_day=user_daily_bytes,
        )

    async def _claim_count(self, *predicates: ColumnElement[bool]) -> int:
        return int(
            (
                await self.session.execute(select(func.count()).select_from(IngestRequest).where(*predicates))
            ).scalar_one()
        )

    async def _charge_count(self, *predicates: ColumnElement[bool]) -> int:
        return int(
            (
                await self.session.execute(select(func.count()).select_from(IngestUsageCharge).where(*predicates))
            ).scalar_one()
        )

    async def _charged_bytes(self, *predicates: ColumnElement[bool]) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.coalesce(func.sum(IngestUsageCharge.accepted_bytes), 0)).where(*predicates)
                )
            ).scalar_one()
        )

    async def _accepted_bytes(self, *predicates: ColumnElement[bool]) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.coalesce(func.sum(IngestRequest.accepted_bytes), 0)).where(*predicates)
                )
            ).scalar_one()
        )

    async def _retained_bytes(self, *, user_id: int | None = None) -> int:
        statement = (
            select(func.coalesce(func.sum(ScannerArtifact.size_bytes), 0))
            .select_from(ScannerArtifact)
            .join(ScannerRun, ScannerRun.id == ScannerArtifact.scanner_run_id)
            .join(Run, Run.run_id == ScannerRun.run_id)
            .where(Run.origin == "local")
        )
        if user_id is not None:
            statement = statement.where(Run.submitted_by_user_id == user_id)
        return int((await self.session.execute(statement)).scalar_one())


def _retry_after(decision: QuotaDecision) -> int | None:
    if decision is QuotaDecision.TOKEN_HOURLY_RATE:
        return 3600
    if decision in {QuotaDecision.USER_DAILY_RATE, QuotaDecision.USER_DAILY_BYTES}:
        return 86_400
    if decision in {
        QuotaDecision.TOKEN_INFLIGHT,
        QuotaDecision.USER_INFLIGHT,
        QuotaDecision.INSTANCE_INFLIGHT,
        QuotaDecision.SHARED_INSTANCE_INFLIGHT,
    }:
        return 30
    return None


def _local_no_work(row: IngestRequest, command: QuotaCommand, *, now: dt.datetime) -> bool:
    tombstone_expiry = _aware(row.tombstone_expires_at)
    if row.state == "tombstoned":
        return tombstone_expiry is None or tombstone_expiry > now
    if row.project_id != command.project_id or row.payload_hash != command.payload_hash:
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
        raise ValueError("quota reservation requires a canonical project and payload hash")
    try:
        parsed = uuid.UUID(correlation_id)
    except ValueError as exc:
        raise ValueError("quota reservation requires a canonical correlation ID") from exc
    if str(parsed) != correlation_id:
        raise ValueError("quota reservation requires a canonical correlation ID")


__all__ = ["SqlAlchemyUsageQuotaRepository"]
