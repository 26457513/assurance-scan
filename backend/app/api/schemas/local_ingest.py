"""Transport-neutral inputs and outputs for the local-ingest HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol

from app.modules.atomic.access.scan_token import ScanTokenPrincipal


@dataclass(frozen=True)
class LocalScanIngestCommand:
    """A fully bounded and validated v1 upload passed to the ingest workflow."""

    principal: ScanTokenPrincipal
    correlation_id: str
    idempotency_key: str
    metadata: Mapping[str, Any]
    findings: Mapping[str, Any]
    accepted_bytes: int
    findings_bytes: bytes = field(repr=False)
    sarif_bytes: bytes | None = field(default=None, repr=False)
    sbom_bytes: bytes | None = field(default=None, repr=False)
    payload_hash: str = field(default="", repr=False)


class LocalScanIngestOutcome(StrEnum):
    """Durable claim outcomes with distinct HTTP success semantics."""

    CREATED = "created"
    REPLAYED = "replayed"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True)
class LocalScanIngestResult:
    """Workflow result rendered by the HTTP boundary."""

    outcome: LocalScanIngestOutcome
    run_id: str | None
    project_id: int | None
    repository: str
    run_url: str | None
    status: str
    status_url: str | None = None
    retry_after_seconds: int | None = None


class LocalScanIngestWorkflow(Protocol):
    """Narrow dependency implemented by the source-neutral ingest workflow."""

    async def ingest_local_scan(
        self,
        command: LocalScanIngestCommand,
    ) -> LocalScanIngestResult:
        """Atomically claim and persist one validated local scan."""


class LocalScanWorkflowError(Exception):
    """Stable expected rejection raised by an ingest workflow implementation."""

    def __init__(
        self,
        *,
        status: int,
        code: str,
        title: str,
        detail: str,
        retryable: bool = False,
        limits: Mapping[str, int] | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.retryable = retryable
        self.limits = dict(limits or {})
        self.retry_after_seconds = retry_after_seconds


__all__ = [
    "LocalScanIngestCommand",
    "LocalScanIngestOutcome",
    "LocalScanIngestResult",
    "LocalScanIngestWorkflow",
    "LocalScanWorkflowError",
]
