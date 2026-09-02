"""Ports and commands for authenticated GitHub Actions result ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.modules.atomic.ingestion.idempotency_guard import (
    GithubIdempotencyClaim,
    GithubIdempotencyRepositoryPort,
)
from app.modules.atomic.ingestion.result_persister import ResultPersistencePort
from app.modules.workflows.result_ingest_v2_contract import ValidatedEnvelopeV2


@dataclass(frozen=True)
class GithubIngestCommand:
    """Validated v2 envelope plus server-authenticated GitHub identity."""

    project_id: int
    repository: str
    github_repository_id: int
    github_owner_id: int
    github_run_id: int
    github_run_attempt: int
    accepted_bytes: int
    envelope: ValidatedEnvelopeV2
    public_base_url: str = ""


class GithubIngestOutcome(StrEnum):
    CREATED = "created"
    REPLAYED = "replayed"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True)
class GithubIngestResult:
    outcome: GithubIngestOutcome
    run_id: str | None
    project_id: int
    repository: str
    run_url: str | None
    status: str
    status_url: str | None = None
    retry_after_seconds: int | None = None


class GithubIngestError(Exception):
    """Stable expected rejection for the future HTTP adapter."""

    def __init__(self, *, status: int, code: str, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


class GithubClaimCompletingPersistencePort(ResultPersistencePort, Protocol):
    async def get(self, run_id: str) -> object | None: ...

    def bind_claim(self, claim: GithubIdempotencyClaim) -> None: ...


@dataclass(frozen=True)
class GithubIngestDependencies:
    claims: GithubIdempotencyRepositoryPort
    persistence: GithubClaimCompletingPersistencePort


__all__ = [
    "GithubClaimCompletingPersistencePort",
    "GithubIngestCommand",
    "GithubIngestDependencies",
    "GithubIngestError",
    "GithubIngestOutcome",
    "GithubIngestResult",
]
