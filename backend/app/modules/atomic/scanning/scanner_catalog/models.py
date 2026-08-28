"""Contracts for scanner configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


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
    tool_version: str = ""
    platform_digests: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: int = 1800
    network: str = "none"
    read_only: bool = True
    user: str | None = None
    tmpfs: tuple[str, ...] = ("/tmp:rw,noexec,nosuid,size=256m",)
    cap_drop: tuple[str, ...] = ("ALL",)
    memory_mib: int = 2048
    cpus: float = 2.0
    no_new_privileges: bool = True


@dataclass(frozen=True)
class ScannerReleaseSet:
    """Reviewed manifest identity and qualification contract."""

    schema_version: int
    name: str
    sha256: str
    required_platforms: tuple[str, ...]
    vulnerability_database_max_age_hours: int
    semgrep_policy_path: str
    semgrep_policy_container_path: str
    semgrep_policy_sha256: str


__all__ = ["ScannerConfig", "ScannerReleaseSet"]
