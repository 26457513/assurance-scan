"""Contracts for canonical repository identity handling."""

from __future__ import annotations

from typing import Any, TypedDict


class InvalidRepositoryIdentityError(ValueError):
    """Raised when a value cannot identify a supported repository."""


class ProjectSummary(TypedDict, total=False):
    """Project-list row consumed and returned by alias reconciliation.

    ``total=False`` intentionally preserves the route's existing extensible
    dictionary response. The keys used by reconciliation are documented here;
    unrelated route fields pass through unchanged.
    """

    project_path: str
    run_count: int
    last_scan_at: Any | None
    has_catalogue: bool
    github_project: str
