"""Ports exposed by the source-neutral result-ingestion workflow."""
from typing import Protocol

from app.modules.atomic.ingestion.result_persister import ResultPersistencePort


class IngestPersistencePort(ResultPersistencePort, Protocol):
    """Lookup, persistence, and transaction boundary required by ingestion."""

    async def get(self, run_id: str) -> object | None: ...


__all__ = ["IngestPersistencePort"]
