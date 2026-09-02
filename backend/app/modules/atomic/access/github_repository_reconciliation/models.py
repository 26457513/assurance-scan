"""Persistence-neutral GitHub installation and repository snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class GithubAccountType(StrEnum):
    USER = "user"
    ORGANIZATION = "organization"
    ENTERPRISE = "enterprise"


class GithubSelection(StrEnum):
    ALL = "all"
    SELECTED = "selected"


class GithubRepositoryVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"


@dataclass(frozen=True)
class GithubRepositorySnapshot:
    github_repository_id: int
    github_owner_id: int
    full_name: str
    default_branch: str
    visibility: GithubRepositoryVisibility
    archived: bool
    disabled: bool


@dataclass(frozen=True)
class GithubInstallationSnapshot:
    github_installation_id: int
    github_owner_id: int
    owner_login: str
    account_type: GithubAccountType
    repository_selection: GithubSelection
    suspended_at: datetime | None
    deleted_at: datetime | None
    repositories_etag: str | None
    reconciliation_cursor: str | None
    repositories: tuple[GithubRepositorySnapshot, ...]


@dataclass(frozen=True)
class ReconciliationResult:
    installation_id: int
    enabled_repository_ids: tuple[int, ...]
    disabled_repository_ids: tuple[int, ...]
    removed_repository_ids: tuple[int, ...]
    invalidated_project_ids: tuple[int, ...]


class ReconciliationValidationError(ValueError):
    """Authoritative GitHub metadata is incomplete, inconsistent, or ambiguous."""
