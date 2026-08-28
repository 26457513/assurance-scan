"""Contracts for repository identity and revision discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(frozen=True)
class GitCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes = b""


class GitCommandPort(Protocol):
    def run(self, arguments: Sequence[str], *, cwd: Path) -> GitCommandResult:
        """Run Git with cwd also configured as an explicit safe directory."""


@dataclass(frozen=True)
class GitRepositoryMetadata:
    repository: str
    branch: str | None
    commit: str
    git_object_format: str
    working_tree_dirty: bool
    project_override: str | None = None


class GitMetadataError(ValueError):
    """The checkout or repository identity is unavailable or unsafe."""


__all__ = ["GitCommandPort", "GitCommandResult", "GitMetadataError", "GitRepositoryMetadata"]
