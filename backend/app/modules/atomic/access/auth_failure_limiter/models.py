"""Framework-free scan-token authentication failure limits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FailureLimitDecision:
    allowed: bool
    retry_after_seconds: int | None = None


__all__ = ["FailureLimitDecision"]
