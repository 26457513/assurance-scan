"""Contracts for ingestion idempotency checks."""
from __future__ import annotations

from typing import Protocol


class RunLookup(Protocol):
    async def get(self, run_id: str) -> object | None: ...
