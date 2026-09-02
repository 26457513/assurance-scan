"""Transport-neutral contracts for a single GitHub OIDC upload attempt."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol


@dataclass(frozen=True)
class GithubUploadBundle:
    root: Path = field(repr=False)
    parts: Mapping[str, Path] = field(repr=False)
    idempotency_key: str
    payload_hash: str


@dataclass(frozen=True)
class GithubUploadConfig:
    base_url: str
    oidc_jwt: str = field(repr=False)
    connect_timeout_seconds: float = 10.0
    response_timeout_seconds: float = 60.0
    allow_loopback_http: bool = False


@dataclass(frozen=True)
class GithubUploadResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes = field(repr=False)


@dataclass(frozen=True)
class GithubUploadResult:
    status: int
    code: str
    retryable: bool


class GithubUploadTransport(Protocol):
    def post(
        self,
        endpoint: str,
        bundle: GithubUploadBundle,
        config: GithubUploadConfig,
    ) -> GithubUploadResponse: ...


class GithubUploadError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class GithubUploadNetworkError(GithubUploadError):
    def __init__(self) -> None:
        super().__init__("network_error", retryable=True)


class JwtInput(Protocol):
    def read(self, size: int = -1) -> bytes: ...


__all__ = [
    "GithubUploadBundle",
    "GithubUploadConfig",
    "GithubUploadError",
    "GithubUploadNetworkError",
    "GithubUploadResponse",
    "GithubUploadResult",
    "GithubUploadTransport",
    "JwtInput",
]
