"""Contracts exposed by the GitHub result-ingestion workflow."""
from typing import Protocol

from app.modules.atomic.ingestion.idempotency_guard import RunLookup
from app.modules.atomic.ingestion.result_persister import ResultPersistencePort
from app.modules.shared.contracts.ingest import IngestStatus


class IngestPersistencePort(RunLookup, ResultPersistencePort, Protocol):
    """Combined lookup and persistence boundary required by this workflow."""


__all__ = ["IngestPersistencePort", "IngestStatus"]
