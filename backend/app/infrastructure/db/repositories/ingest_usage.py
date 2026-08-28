"""Serialized SQLAlchemy usage-quota adapter for local ingestion."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.db.models import IngestRequest, Run, ScannerArtifact, ScannerRun, User
from app.modules.atomic.ingestion.usage_quota import (
    QuotaCommand,
    QuotaDecision,
    QuotaResult,
    UsageReservation,
    UsageSnapshot,
    decide_usage_quota,
)
from app.modules.shared.contracts.local_scan import UsageLimits

QUOTA_LOCK_SESSION_KEY = "local_ingest_quota_lock"


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
        now: dt.datetime,
    ) -> QuotaResult:
        await self._begin_write(command.user_id)
        self.session.info[QUOTA_LOCK_SESSION_KEY] = True
        existing = (
            await self.session.execute(
                select(IngestRequest.id).where(
                    IngestRequest.submitted_by_user_id == command.user_id,
                    IngestRequest.client_request_id == command.client_request_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return self._allowed(command, now)
        snapshot = await self._snapshot(command, now=now)
        decision = decide_usage_quota(command, snapshot, limits=limits)
        if decision is not QuotaDecision.ALLOWED:
            await self.session.rollback()
            self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
            return QuotaResult(decision, retry_after_seconds=_retry_after(decision))
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

    async def _begin_write(self, user_id: int) -> None:
        if self.session.in_transaction():
            raise RuntimeError("quota reservation requires a clean session")
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))
            return
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())

    async def _snapshot(self, command: QuotaCommand, *, now: dt.datetime) -> UsageSnapshot:
        hour_start = now - dt.timedelta(hours=1)
        day_start = now.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        token_uploads = await self._claim_count(
            IngestRequest.submitting_token_id == command.token_id,
            IngestRequest.created_at >= hour_start,
        )
        user_uploads = await self._claim_count(
            IngestRequest.submitted_by_user_id == command.user_id,
            IngestRequest.created_at >= day_start,
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
        instance_inflight = await self._claim_count(
            IngestRequest.state == "processing", IngestRequest.lease_expires_at > now
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
        user_daily_bytes = await self._accepted_bytes(
            IngestRequest.submitted_by_user_id == command.user_id,
            IngestRequest.created_at >= day_start,
        )
        return UsageSnapshot(
            token_uploads_hour=token_uploads,
            user_uploads_day=user_uploads,
            token_inflight=token_inflight,
            user_inflight=user_inflight,
            instance_inflight=instance_inflight,
            user_retained_bytes=user_retained + user_pending,
            instance_retained_bytes=instance_retained + instance_pending,
            user_accepted_bytes_day=user_daily_bytes,
        )

    async def _claim_count(self, *predicates: ColumnElement[bool]) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count()).select_from(IngestRequest).where(*predicates)
                )
            ).scalar_one()
        )

    async def _accepted_bytes(self, *predicates: ColumnElement[bool]) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.coalesce(func.sum(IngestRequest.accepted_bytes), 0)).where(
                        *predicates
                    )
                )
            ).scalar_one()
        )

    async def _retained_bytes(self, *, user_id: int | None = None) -> int:
        statement = (
            select(func.coalesce(func.sum(ScannerArtifact.size_bytes), 0))
            .select_from(ScannerArtifact)
            .join(ScannerRun, ScannerRun.id == ScannerArtifact.scanner_run_id)
            .join(Run, Run.run_id == ScannerRun.run_id)
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
    }:
        return 30
    return None


__all__ = ["QUOTA_LOCK_SESSION_KEY", "SqlAlchemyUsageQuotaRepository"]
