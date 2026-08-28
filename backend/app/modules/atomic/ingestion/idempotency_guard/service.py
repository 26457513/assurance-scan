"""Atomic idempotency checks for result ingestion."""
from __future__ import annotations

from .models import RunLookup


async def run_exists(repository: RunLookup, run_id: str) -> bool:
    """Return whether a run with the source-derived identifier already exists."""

    return await repository.get(run_id) is not None
