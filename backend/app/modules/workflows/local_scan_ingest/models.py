"""Ports and source-neutral commands for authenticated local ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol

from app.modules.atomic.ingestion.idempotency_guard import (
    IdempotencyClaim,
    IdempotencyRepositoryPort,
)
from app.modules.atomic.ingestion.ingest_attempt import (
    IngestAttemptRecord,
    IngestAttemptRepositoryPort,
)
from app.modules.atomic.ingestion.result_persister import ResultPersistencePort
from app.modules.atomic.ingestion.usage_quota import UsageQuotaRepositoryPort
from app.modules.shared.contracts.ingest import ResolvedProject
from app.modules.shared.contracts.local_scan import USAGE_LIMITS, UsageLimits
from app.modules.shared.contracts.ingest_v2 import SHARED_USAGE_LIMITS_V2, SharedUsageLimitsV2


@dataclass(frozen=True)
class LocalScanCommand:
    """Validated upload plus the server-authenticated principal."""

    user_id: int
    correlation_id: str
    token_id: str
    token_label: str
    token_scopes: frozenset[str]
    request_id: str
    metadata: Mapping[str, Any]
    findings: Mapping[str, Any]
    accepted_bytes: int
    payload_hash: str = field(repr=False)
    findings_bytes: bytes = field(repr=False)
    sarif_bytes: bytes | None = field(default=None, repr=False)
    sbom_bytes: bytes | None = field(default=None, repr=False)
    public_base_url: str = ""


class LocalScanOutcome(StrEnum):
    CREATED = "created"
    REPLAYED = "replayed"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True)
class LocalScanResult:
    outcome: LocalScanOutcome
    run_id: str | None
    project_id: int
    repository: str
    run_url: str | None
    status: str
    status_url: str | None = None
    retry_after_seconds: int | None = None


class LocalScanIngestError(Exception):
    """Stable expected rejection rendered by the HTTP adapter."""

    def __init__(
        self,
        *,
        status: int,
        code: str,
        title: str,
        detail: str,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class ProjectResolution:
    """Repository selector result without leaking hidden-project details."""

    project: ResolvedProject | None
    hidden: bool = False
    can_upload: bool = False


class LocalProjectResolverPort(Protocol):
    async def resolve(self, repository: str, user_id: int) -> ProjectResolution: ...


class ClaimCompletingPersistencePort(ResultPersistencePort, Protocol):
    """Result persistence that can stage claim completion before its commit."""

    async def get(self, run_id: str) -> object | None: ...

    def bind_claim(self, claim: IdempotencyClaim) -> None: ...

    def bind_attempt(self, attempt: IngestAttemptRecord) -> None: ...


@dataclass(frozen=True)
class LocalScanDependencies:
    projects: LocalProjectResolverPort
    quotas: UsageQuotaRepositoryPort
    claims: IdempotencyRepositoryPort
    attempts: IngestAttemptRepositoryPort
    persistence: ClaimCompletingPersistencePort
    usage_limits: UsageLimits = USAGE_LIMITS
    shared_usage_limits: SharedUsageLimitsV2 = SHARED_USAGE_LIMITS_V2


__all__ = [
    "ClaimCompletingPersistencePort",
    "LocalProjectResolverPort",
    "LocalScanCommand",
    "LocalScanDependencies",
    "LocalScanIngestError",
    "LocalScanOutcome",
    "LocalScanResult",
    "ProjectResolution",
]
