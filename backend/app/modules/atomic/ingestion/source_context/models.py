"""Limits and output values for deterministic source-context extraction."""
from __future__ import annotations

from dataclasses import dataclass

from app.modules.shared.contracts.findings import FindingPayload
from app.modules.shared.contracts.source_context import SourceContextPayload


REDACTION_VERSION = 1


@dataclass(frozen=True)
class SourceContextLimits:
    """Hard limits applied before context can reach an outbox or network."""

    max_windows: int = 500
    max_lines: int = 11
    max_line_bytes: int = 1024
    max_window_bytes: int = 8 * 1024
    max_request_bytes: int = 2 * 1024 * 1024
    max_source_file_bytes: int = 1024 * 1024


@dataclass(frozen=True)
class SourceContextExtraction:
    """Findings with stable keys plus their deduplicated context windows."""

    findings: tuple[FindingPayload, ...]
    contexts: tuple[SourceContextPayload, ...]


__all__ = ["REDACTION_VERSION", "SourceContextExtraction", "SourceContextLimits"]
