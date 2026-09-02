"""Transactional SQLAlchemy adapter for leased local-ingest claims."""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from typing import Any, cast

from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.db.models import IngestRequest, User
from app.infrastructure.db.repositories.ingest_quota_lock import QUOTA_LOCK_SESSION_KEY
from app.modules.atomic.ingestion.idempotency_guard import (
    ClaimCommand,
    ClaimDecision,
    ClaimResult,
    IdempotencyClaim,
)


class SqlAlchemyIdempotencyRepository:
    """Serialize claims and fence stale workers on SQLite and row-locking databases."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def acquire(
        self,
        command: ClaimCommand,
        *,
        now: dt.datetime,
        lease_expires_at: dt.datetime,
    ) -> ClaimResult:
        owns_transaction = not self.session.in_transaction()
        if owns_transaction:
            await self._begin_write(command.user_id)
        elif not self.session.info.get(QUOTA_LOCK_SESSION_KEY):
            raise RuntimeError("idempotency acquisition requires a clean session or quota lock")
        row = await self._get_locked(command.user_id, command.client_request_id)
        lease_id = str(uuid.UUID(bytes=secrets.token_bytes(16), version=4))
        if row is None:
            self.session.add(
                IngestRequest(
                    submitted_by_user_id=command.user_id,
                    submitting_token_id=command.token_id,
                    client_request_id=command.client_request_id,
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
                # A concurrent insert won. Re-enter once and decide from its row.
                return await self.acquire(command, now=now, lease_expires_at=lease_expires_at)
            return ClaimResult(ClaimDecision.ACQUIRED, lease_id, lease_expires_at)

        result = self._existing_decision(row, command, now=now)
        if result is not None:
            await self.session.rollback()
            self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
            return result

        stale = row.state == "processing"
        row.state = "processing"
        row.submitting_token_id = command.token_id
        row.accepted_bytes = command.accepted_bytes
        row.run_id = None
        row.lease_id = lease_id
        row.lease_expires_at = lease_expires_at
        row.tombstoned_at = None
        row.tombstone_expires_at = None
        row.updated_at = now
        await self.session.commit()
        self.session.info.pop(QUOTA_LOCK_SESSION_KEY, None)
        decision = ClaimDecision.STALE_TAKEOVER if stale else ClaimDecision.ACQUIRED
        return ClaimResult(decision, lease_id, lease_expires_at)

    async def heartbeat(
        self,
        claim: IdempotencyClaim,
        *,
        new_lease_expires_at: dt.datetime,
    ) -> bool:
        result = cast(CursorResult[Any], await self.session.execute(
            update(IngestRequest)
            .where(*self._owned_predicates(claim))
            .values(lease_expires_at=new_lease_expires_at, updated_at=dt.datetime.now(dt.timezone.utc))
        ))
        await self.session.commit()
        return bool(result.rowcount)

    async def complete(
        self,
        claim: IdempotencyClaim,
        *,
        run_id: str,
        now: dt.datetime,
    ) -> bool:
        """Fence completion and flush it into the caller's run transaction."""
        result = cast(CursorResult[Any], await self.session.execute(
            update(IngestRequest)
            .where(*self._owned_predicates(claim))
            .values(
                state="completed",
                run_id=run_id,
                lease_id=None,
                lease_expires_at=None,
                updated_at=now,
            )
        ))
        await self.session.flush()
        return bool(result.rowcount)

    async def fail(self, claim: IdempotencyClaim, *, now: dt.datetime) -> bool:
        result = cast(CursorResult[Any], await self.session.execute(
            update(IngestRequest)
            .where(*self._owned_predicates(claim))
            .values(
                state="failed",
                run_id=None,
                lease_id=None,
                lease_expires_at=None,
                updated_at=now,
            )
        ))
        await self.session.commit()
        return bool(result.rowcount)

    async def tombstone_completed(
        self,
        *,
        run_id: str,
        now: dt.datetime,
        expires_at: dt.datetime,
    ) -> bool:
        """Detach a claim before run deletion in the caller-owned transaction."""
        result = cast(CursorResult[Any], await self.session.execute(
            update(IngestRequest)
            .where(
                IngestRequest.run_id == run_id,
                IngestRequest.state == "completed",
            )
            .values(
                state="tombstoned",
                run_id=None,
                tombstoned_at=now,
                tombstone_expires_at=expires_at,
                updated_at=now,
            )
        ))
        await self.session.flush()
        return bool(result.rowcount)

    async def purge_expired_tombstones(self, *, now: dt.datetime) -> int:
        result = cast(CursorResult[Any], await self.session.execute(
            delete(IngestRequest).where(
                IngestRequest.state == "tombstoned",
                IngestRequest.tombstone_expires_at <= now,
            )
        ))
        await self.session.commit()
        return int(result.rowcount or 0)

    async def _begin_write(self, user_id: int) -> None:
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))
            return
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())

    async def _get_locked(self, user_id: int, request_id: str) -> IngestRequest | None:
        statement = select(IngestRequest).where(
            IngestRequest.submitted_by_user_id == user_id,
            IngestRequest.client_request_id == request_id,
        )
        if self.session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    @staticmethod
    def _existing_decision(
        row: IngestRequest,
        command: ClaimCommand,
        *,
        now: dt.datetime,
    ) -> ClaimResult | None:
        if row.project_id != command.project_id or row.payload_hash != command.payload_hash:
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
    def _owned_predicates(claim: IdempotencyClaim) -> tuple[ColumnElement[bool], ...]:
        return (
            IngestRequest.submitted_by_user_id == claim.user_id,
            IngestRequest.client_request_id == claim.client_request_id,
            IngestRequest.payload_hash == claim.payload_hash,
            IngestRequest.state == "processing",
            IngestRequest.lease_id == claim.lease_id,
        )


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value


__all__ = ["SqlAlchemyIdempotencyRepository"]
