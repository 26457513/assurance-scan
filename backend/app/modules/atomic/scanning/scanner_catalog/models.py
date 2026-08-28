"""Contracts for scanner configuration."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScannerConfig:
    """Everything required to spawn and parse one scanner."""

    kind: str
    image: str
    command: tuple[str, ...]
    output_kind: str
    success_exit_codes: tuple[int, ...] = (0,)
    extra_mounts: dict[str, str] = field(default_factory=dict)
    working_dir: str = "/src"
    env: dict[str, str] = field(default_factory=dict)
    produces_findings: bool = True
    group: str = "code"
