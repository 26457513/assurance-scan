"""Contracts returned by the Docker execution port."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScannerResult:
    """Captured outcome from a scanner container."""

    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def ok(self) -> bool:
        return self.returncode == 0
