"""Contracts exposed by the GitHub result-ingestion workflow."""
from typing import Protocol

from app.modules.atomic.ingestion.idempotency_guard import RunLookup
from app.modules.atomic.ingestion.result_persister import ResultPersistencePort
from app.modules.shared.contracts.ingest import IngestStatus, ResolvedGitHubProject


class IngestPersistencePort(RunLookup, ResultPersistencePort, Protocol):
    """Combined lookup and persistence boundary required by this workflow."""

    async def resolve_github_project(self, repository: str) -> ResolvedGitHubProject | None: ...


__all__ = ["IngestPersistencePort", "IngestStatus", "ResolvedGitHubProject"]
