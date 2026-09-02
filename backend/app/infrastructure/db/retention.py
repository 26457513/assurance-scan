"""Transactional retention and deletion preparation for scan data."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Sequence, cast

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    ApiToken,
    GithubWebhookDelivery,
    GithubIngestRequest,
    IngestAttempt,
    IngestRequest,
    IngestUsageCharge,
    Run,
    ScannerArtifact,
)
from app.infrastructure.db.repositories.ingest_requests import SqlAlchemyIdempotencyRepository
from app.infrastructure.db.repositories.github_ingest_requests import (
    SqlAlchemyGithubIdempotencyRepository,
)
from app.modules.shared.contracts.local_scan import RETENTION_DAYS


RETENTION_BATCH_SIZE = 500


@dataclass(frozen=True)
class RetentionCleanupResult:
    raw_artifacts: int
    runs: int
    tombstones: int
    token_audits: int
    webhook_deliveries: int
    ingest_attempts: int
    usage_charges: int


async def prepare_runs_for_deletion(
    session: AsyncSession,
    run_ids: Sequence[str],
    *,
    now: dt.datetime | None = None,
) -> int:
    """Convert completed claims to tombstones before their runs are deleted."""
    timestamp = now or dt.datetime.now(dt.timezone.utc)
    expiry = timestamp + dt.timedelta(days=RETENTION_DAYS.deletion_tombstone)
    claims = SqlAlchemyIdempotencyRepository(session)
    github_claims = SqlAlchemyGithubIdempotencyRepository(session)
    converted = 0
    for run_id in run_ids:
        converted += int(
            await claims.tombstone_completed(
                run_id=run_id,
                now=timestamp,
                expires_at=expiry,
            )
        )
        converted += int(
            await github_claims.tombstone_completed(
                run_id=run_id,
                now=timestamp,
                expires_at=expiry,
            )
        )
    return converted


async def run_retention_cleanup(
    session: AsyncSession,
    *,
    now: dt.datetime | None = None,
) -> RetentionCleanupResult:
    """Apply bounded scan, credential and webhook retention in one transaction."""
    timestamp = now or dt.datetime.now(dt.timezone.utc)
    raw_cutoff = timestamp - dt.timedelta(days=RETENTION_DAYS.raw_artifacts)
    normalized_cutoff = timestamp - dt.timedelta(days=RETENTION_DAYS.normalized_history)
    audit_cutoff = timestamp - dt.timedelta(days=RETENTION_DAYS.token_audit_after_inactive)

    raw_ids = (
        select(ScannerArtifact.id)
        .where(ScannerArtifact.created_at <= raw_cutoff)
        .order_by(ScannerArtifact.created_at, ScannerArtifact.id)
        .limit(RETENTION_BATCH_SIZE)
    )
    raw_result = await session.execute(
        delete(ScannerArtifact).where(ScannerArtifact.id.in_(raw_ids)).execution_options(synchronize_session=False)
    )
    expired_run_ids = tuple(
        (
            await session.execute(
                select(Run.run_id)
                .where(
                    or_(
                        Run.completed_at <= normalized_cutoff,
                        (Run.completed_at.is_(None) & (Run.started_at <= normalized_cutoff)),
                    )
                )
                .order_by(Run.started_at, Run.run_id)
                .limit(RETENTION_BATCH_SIZE)
            )
        ).scalars()
    )
    await prepare_runs_for_deletion(session, expired_run_ids, now=timestamp)
    run_result = await session.execute(
        delete(Run).where(Run.run_id.in_(expired_run_ids)).execution_options(synchronize_session=False)
    )
    tombstone_ids = (
        select(IngestRequest.id)
        .where(
            IngestRequest.state == "tombstoned",
            IngestRequest.tombstone_expires_at <= timestamp,
        )
        .order_by(IngestRequest.tombstone_expires_at, IngestRequest.id)
        .limit(RETENTION_BATCH_SIZE)
    )
    tombstone_result = await session.execute(
        delete(IngestRequest).where(IngestRequest.id.in_(tombstone_ids)).execution_options(synchronize_session=False)
    )
    github_tombstone_ids = (
        select(GithubIngestRequest.id)
        .where(
            GithubIngestRequest.state == "tombstoned",
            GithubIngestRequest.tombstone_expires_at <= timestamp,
        )
        .order_by(GithubIngestRequest.tombstone_expires_at, GithubIngestRequest.id)
        .limit(RETENTION_BATCH_SIZE)
    )
    github_tombstone_result = await session.execute(
        delete(GithubIngestRequest)
        .where(GithubIngestRequest.id.in_(github_tombstone_ids))
        .execution_options(synchronize_session=False)
    )
    token_ids = (
        select(ApiToken.id)
        .where(
            or_(ApiToken.revoked_at <= audit_cutoff, ApiToken.expires_at <= audit_cutoff),
            ~exists().where(Run.submitting_token_id == ApiToken.id),
            ~exists().where(IngestRequest.submitting_token_id == ApiToken.id),
        )
        .order_by(ApiToken.expires_at, ApiToken.id)
        .limit(RETENTION_BATCH_SIZE)
    )
    token_result = await session.execute(
        delete(ApiToken).where(ApiToken.id.in_(token_ids)).execution_options(synchronize_session=False)
    )
    webhook_ids = (
        select(GithubWebhookDelivery.delivery_id)
        .where(GithubWebhookDelivery.expires_at <= timestamp)
        .order_by(GithubWebhookDelivery.expires_at, GithubWebhookDelivery.delivery_id)
        .limit(RETENTION_BATCH_SIZE)
    )
    webhook_result = await session.execute(
        delete(GithubWebhookDelivery)
        .where(GithubWebhookDelivery.delivery_id.in_(webhook_ids))
        .execution_options(synchronize_session=False)
    )
    attempt_ids = (
        select(IngestAttempt.id)
        .where(IngestAttempt.expires_at <= timestamp)
        .order_by(IngestAttempt.expires_at, IngestAttempt.id)
        .limit(RETENTION_BATCH_SIZE)
    )
    attempt_result = await session.execute(
        delete(IngestAttempt).where(IngestAttempt.id.in_(attempt_ids)).execution_options(synchronize_session=False)
    )
    charge_ids = (
        select(IngestUsageCharge.id)
        .where(IngestUsageCharge.expires_at <= timestamp)
        .order_by(IngestUsageCharge.expires_at, IngestUsageCharge.id)
        .limit(RETENTION_BATCH_SIZE)
    )
    charge_result = await session.execute(
        delete(IngestUsageCharge)
        .where(IngestUsageCharge.id.in_(charge_ids))
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return RetentionCleanupResult(
        raw_artifacts=int(cast(CursorResult[Any], raw_result).rowcount or 0),
        runs=int(cast(CursorResult[Any], run_result).rowcount or 0),
        tombstones=(
            int(cast(CursorResult[Any], tombstone_result).rowcount or 0)
            + int(cast(CursorResult[Any], github_tombstone_result).rowcount or 0)
        ),
        token_audits=int(cast(CursorResult[Any], token_result).rowcount or 0),
        webhook_deliveries=int(cast(CursorResult[Any], webhook_result).rowcount or 0),
        ingest_attempts=int(cast(CursorResult[Any], attempt_result).rowcount or 0),
        usage_charges=int(cast(CursorResult[Any], charge_result).rowcount or 0),
    )


__all__ = [
    "RetentionCleanupResult",
    "RETENTION_BATCH_SIZE",
    "prepare_runs_for_deletion",
    "run_retention_cleanup",
]
