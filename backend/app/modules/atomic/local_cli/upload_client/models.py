"""Transport-neutral models for authenticated local-scan uploads."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping


class UploadDisposition(StrEnum):
    UPLOADED = "uploaded"
    REPLAYED = "replayed"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True)
class UploadClientConfig:
    base_url: str
    token: str = field(repr=False)
    custom_ca_file: Path | None = None
    allow_loopback_http: bool = False
    connect_timeout_seconds: float = 10.0
    response_timeout_seconds: float = 60.0
    max_attempts: int = 4
    max_retry_delay_seconds: int = 60


@dataclass(frozen=True)
class UploadBundle:
    """Owner-only outbox files forming one immutable retryable request."""

    request_id: str
    metadata_path: Path = field(repr=False)
    findings_path: Path = field(repr=False)
    sarif_path: Path | None = field(default=None, repr=False)
    sbom_path: Path | None = field(default=None, repr=False)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes = field(repr=False)


@dataclass(frozen=True)
class UploadResult:
    disposition: UploadDisposition
    status: int
    run_id: str | None
    project_id: int | None
    run_url: str | None
    retry_after_seconds: int | None = None


class UploadClientError(Exception):
    """Safe client error that never embeds credentials, payloads, or host paths."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UploadNetworkError(UploadClientError):
    pass


class UploadRejectedError(UploadClientError):
    def __init__(self, code: str, *, status: int) -> None:
        super().__init__(code, f"upload rejected by server ({code})")
        self.status = status


__all__ = [
    "HttpResponse",
    "UploadBundle",
    "UploadClientConfig",
    "UploadClientError",
    "UploadDisposition",
    "UploadNetworkError",
    "UploadRejectedError",
    "UploadResult",
]
