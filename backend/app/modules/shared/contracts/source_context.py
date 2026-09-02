"""Source-context contracts shared by producers, ingest, and presentation."""
from __future__ import annotations

from typing import Literal, TypedDict


SourceContextProvider = Literal["snapshot"]
SourceContextUnavailableReason = Literal[
    "binary",
    "context_limit",
    "decode_error",
    "file_too_large",
    "invalid_path",
    "missing_file",
    "missing_line",
    "missing_path",
    "not_uploaded",
    "request_limit",
    "untrusted_range",
]


class SourceLinePayload(TypedDict):
    """One numbered, already-redacted source line."""

    number: int
    text: str
    truncated: bool


class SourceContextPayload(TypedDict, total=False):
    """One deduplicated source window referenced by one or more findings."""

    context_key: str
    finding_keys: list[str]
    available: bool
    provider: SourceContextProvider
    path: str
    window_start: int
    window_end: int
    highlight_start: int
    highlight_end: int
    highlight_truncated: bool
    lines: list[SourceLinePayload]
    source_hash: str
    redaction_version: int
    redaction_changed: bool
    unavailable_reason: SourceContextUnavailableReason


__all__ = [
    "SourceContextPayload",
    "SourceContextProvider",
    "SourceContextUnavailableReason",
    "SourceLinePayload",
]
