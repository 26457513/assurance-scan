"""Persistence port for safe ingest-attempt evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import IngestAttemptRecord


class IngestAttemptRepositoryPort(Protocol):
    async def stage(self, record: IngestAttemptRecord) -> None: ...

    async def record(self, record: IngestAttemptRecord) -> None: ...

    async def purge_expired(self, *, now: datetime) -> int: ...


__all__ = ["IngestAttemptRepositoryPort"]
