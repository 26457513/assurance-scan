"""Typed outcomes for local Docker and sibling-mount trust checks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalDockerEndpoint:
    """One accepted local Unix-socket Docker endpoint."""

    raw: str
    socket_path: Path
    rootless: bool


class RuntimeTrustError(ValueError):
    """A local runtime boundary is remote, ambiguous, or unsafe."""


__all__ = ["LocalDockerEndpoint", "RuntimeTrustError"]
