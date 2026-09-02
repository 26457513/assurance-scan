"""Framework-free records for GitHub upload authorization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GithubUploadCandidate:
    github_installation_id: int
    github_repository_id: int
    github_owner_id: int
    project_id: int


__all__ = ["GithubUploadCandidate"]
