"""Ports for durable leased idempotency claims."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import (
    ClaimCommand,
    ClaimResult,
    GithubClaimCommand,
    GithubIdempotencyClaim,
    IdempotencyClaim,
)


class IdempotencyRepositoryPort(Protocol):
    """Atomically enforce claim uniqueness and lease ownership."""

    async def acquire(
        self,
        command: ClaimCommand,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimResult: ...

    async def heartbeat(
        self,
        claim: IdempotencyClaim,
        *,
        new_lease_expires_at: datetime,
    ) -> bool: ...

    async def complete(self, claim: IdempotencyClaim, *, run_id: str, now: datetime) -> bool: ...

    async def fail(self, claim: IdempotencyClaim, *, now: datetime) -> bool: ...

    async def tombstone_completed(
        self,
        *,
        run_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> bool: ...

    async def purge_expired_tombstones(self, *, now: datetime) -> int: ...


class GithubIdempotencyRepositoryPort(Protocol):
    """Atomically enforce uniqueness for a GitHub run attempt."""

    async def acquire(
        self,
        command: GithubClaimCommand,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimResult: ...

    async def heartbeat(
        self,
        claim: GithubIdempotencyClaim,
        *,
        new_lease_expires_at: datetime,
    ) -> bool: ...

    async def complete(
        self,
        claim: GithubIdempotencyClaim,
        *,
        run_id: str,
        now: datetime,
    ) -> bool: ...

    async def fail(self, claim: GithubIdempotencyClaim, *, now: datetime) -> bool: ...

    async def tombstone_completed(
        self,
        *,
        run_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> bool: ...

    async def purge_expired_tombstones(self, *, now: datetime) -> int: ...


__all__ = ["GithubIdempotencyRepositoryPort", "IdempotencyRepositoryPort"]
