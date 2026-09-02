"""Authenticated principal emitted by the GitHub Actions adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GithubActionsUploadPrincipal:
    project_id: int
    github_repository_id: int
    github_owner_id: int
    github_run_id: int
    github_run_attempt: int


__all__ = ["GithubActionsUploadPrincipal"]
