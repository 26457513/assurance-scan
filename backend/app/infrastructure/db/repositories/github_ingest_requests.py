"""Transactional SQLAlchemy adapter for leased GitHub-ingest claims."""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from typing import Any, cast

from sqlalchemy import delete, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.db.models import GithubIngestRequest, Project
from app.infrastructure.db.repositories.ingest_quota_lock import QUOTA_LOCK_SESSION_KEY
from app.modules.atomic.ingestion.idempotency_guard import (
    ClaimDecision,
    ClaimResult,
    GithubClaimCommand,
    GithubIdempotencyClaim,
)


class SqlAlchemyGithubIdempotencyRepository:
    """Serialize GitHub run-attempt claims and fence stale workers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def acquire(
        self,
        command: GithubClaimCommand,
        *,
        now: dt.datetime,
        lease_expires_at: dt.datetime,
    ) -> ClaimResult:
        if self.session.in_transaction() and not self.session.info.get(QUOTA_LOCK_SESSION_KEY):
            raise RuntimeError("GitHub idempotency acquisition requires a clean session")
        await self._begin_write(command.project_id)
        row = await self._get_locked(command)
        lease_id = str(uuid.UUID(bytes=secrets.token_bytes(16), version=4))
        if row is None:
            self.session.add(
                GithubIngestRequest(
                    github_repository_id=command.github_repository_id,
                    github_owner_id=command.github_owner_id,
                    github_run_id=command.github_run_id,
                    run_attempt=command.run_attempt,
                    project_id=command.project_id,
                    payload_hash=command.payload_hash,
                    accepted_bytes=command.accepted_bytes,
                    state="processing",
                    lease_id=lease_id,
                    lease_expires_at=lease_expires_at,
                    created_at=now,
                    updated_at=now,
                )
            )
            try:
                await self.session.commit()
                self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
            except IntegrityError:
                await self.session.rollback()
                self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
                return await self.acquire(command, now=now, lease_expires_at=lease_expires_at)
            return ClaimResult(ClaimDecision.ACQUIRED, lease_id, lease_expires_at)

        decision = self._existing_decision(row, command, now=now)
        if decision is not None:
            await self.session.rollback()
            self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
            return decision

        stale = row.state == "processing"
        row.state = "processing"
        row.project_id = command.project_id
        row.payload_hash = command.payload_hash
        row.accepted_bytes = command.accepted_bytes
        row.run_id = None
        row.lease_id = lease_id
        row.lease_expires_at = lease_expires_at
        row.tombstoned_at = None
        row.tombstone_expires_at = None
        row.updated_at = now
        await self.session.commit()
        self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
        acquired_decision = ClaimDecision.STALE_TAKEOVER if stale else ClaimDecision.ACQUIRED
        return ClaimResult(acquired_decision, lease_id, lease_expires_at)

    async def heartbeat(
        self,
        claim: GithubIdempotencyClaim,
        *,
        new_lease_expires_at: dt.datetime,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(GithubIngestRequest)
                .where(*self._owned_predicates(claim))
                .values(
                    lease_expires_at=new_lease_expires_at,
                    updated_at=dt.datetime.now(dt.timezone.utc),
                )
            ),
        )
        await self.session.commit()
        return bool(result.rowcount)

    async def complete(
        self,
        claim: GithubIdempotencyClaim,
        *,
        run_id: str,
        now: dt.datetime,
    ) -> bool:
        """Fence completion and flush it into the result transaction."""
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(GithubIngestRequest)
                .where(*self._owned_predicates(claim))
                .values(
                    state="completed",
                    run_id=run_id,
                    lease_id=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            ),
        )
        await self.session.flush()
        return bool(result.rowcount)

    async def fail(self, claim: GithubIdempotencyClaim, *, now: dt.datetime) -> bool:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(GithubIngestRequest)
                .where(*self._owned_predicates(claim))
                .values(
                    state="failed",
                    run_id=None,
                    lease_id=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            ),
        )
        await self.session.commit()
        return bool(result.rowcount)

    async def tombstone_completed(
        self,
        *,
        run_id: str,
        now: dt.datetime,
        expires_at: dt.datetime,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(GithubIngestRequest)
                .where(
                    GithubIngestRequest.run_id == run_id,
                    GithubIngestRequest.state == "completed",
                )
                .values(
                    state="tombstoned",
                    run_id=None,
                    tombstoned_at=now,
                    tombstone_expires_at=expires_at,
                    updated_at=now,
                )
            ),
        )
        await self.session.flush()
        return bool(result.rowcount)

    async def purge_expired_tombstones(self, *, now: dt.datetime) -> int:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                delete(GithubIngestRequest).where(
                    GithubIngestRequest.state == "tombstoned",
                    GithubIngestRequest.tombstone_expires_at <= now,
                )
            ),
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def _begin_write(self, project_id: int) -> None:
        if self.session.in_transaction() and self.session.info.get(QUOTA_LOCK_SESSION_KEY):
            return
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))
            return
        await self.session.execute(select(Project.id).where(Project.id == project_id).with_for_update())

    async def _get_locked(self, command: GithubClaimCommand) -> GithubIngestRequest | None:
        statement = select(GithubIngestRequest).where(
            GithubIngestRequest.github_repository_id == command.github_repository_id,
            GithubIngestRequest.github_run_id == command.github_run_id,
            GithubIngestRequest.run_attempt == command.run_attempt,
        )
        if self.session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    @staticmethod
    def _existing_decision(
        row: GithubIngestRequest,
        command: GithubClaimCommand,
        *,
        now: dt.datetime,
    ) -> ClaimResult | None:
        if (
            row.project_id != command.project_id
            or row.github_owner_id != command.github_owner_id
            or row.payload_hash != command.payload_hash
        ):
            return ClaimResult(ClaimDecision.CONFLICT)
        if row.state == "tombstoned":
            tombstone_expiry = _aware(row.tombstone_expires_at)
            if tombstone_expiry is None or tombstone_expiry > now:
                return ClaimResult(ClaimDecision.TOMBSTONED)
            return None
        if row.state == "completed":
            return ClaimResult(ClaimDecision.REPLAY, run_id=row.run_id)
        lease_expiry = _aware(row.lease_expires_at)
        if row.state == "processing" and (lease_expiry is None or lease_expiry > now):
            return ClaimResult(
                ClaimDecision.IN_PROGRESS,
                lease_id=row.lease_id,
                lease_expires_at=lease_expiry,
            )
        return None

    @staticmethod
    def _owned_predicates(
        claim: GithubIdempotencyClaim,
    ) -> tuple[ColumnElement[bool], ...]:
        return (
            GithubIngestRequest.github_repository_id == claim.github_repository_id,
            GithubIngestRequest.github_run_id == claim.github_run_id,
            GithubIngestRequest.run_attempt == claim.run_attempt,
            GithubIngestRequest.payload_hash == claim.payload_hash,
            GithubIngestRequest.state == "processing",
            GithubIngestRequest.lease_id == claim.lease_id,
        )


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value


__all__ = ["SqlAlchemyGithubIdempotencyRepository"]
