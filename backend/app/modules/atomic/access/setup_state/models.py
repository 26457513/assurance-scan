"""Persistence-neutral version-two Setup projection contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias


class SetupStateKind(StrEnum):
    SIGNED_OUT = "signed_out"
    GITHUB_CONNECTED = "github_connected"
    APPROVAL_PENDING = "approval_pending"
    INSTALLED_NO_REPOSITORIES = "installed_no_repositories"
    REPOSITORY_SELECTION = "repository_selection"
    REPOSITORY_READY = "repository_ready"
    REPOSITORY_READY_WRITE = "repository_ready_write"
    ACCESS_STALE = "access_stale"
    INSTALLATION_SUSPENDED = "installation_suspended"


class SetupRepositoryPermission(StrEnum):
    READ = "read"
    TRIAGE = "triage"
    WRITE = "write"
    MAINTAIN = "maintain"
    ADMIN = "admin"


class SetupReadinessKind(StrEnum):
    NO_SCAN = "no_scan"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class SetupTokenStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True)
class SetupGithubIdentity:
    github_user_id: int
    login: str
    avatar_url: str | None


@dataclass(frozen=True)
class SetupInstallation:
    github_installation_id: int
    github_owner_id: int
    owner_login: str
    account_type: str
    repository_selection: str
    enabled_repository_count: int
    manage_url: str


@dataclass(frozen=True)
class SetupRepository:
    github_repository_id: int
    github_installation_id: int
    project_id: int
    full_name: str
    default_branch: str
    permission: SetupRepositoryPermission
    archived: bool


@dataclass(frozen=True)
class SetupCapabilities:
    can_local_scan: bool
    can_manage: bool


@dataclass(frozen=True)
class NoScanReadiness:
    kind: SetupReadinessKind = SetupReadinessKind.NO_SCAN


@dataclass(frozen=True)
class AcceptedReadiness:
    attempt_id: str
    accepted_at: datetime
    run_id: str
    actions_url: str
    kind: SetupReadinessKind = SetupReadinessKind.ACCEPTED


@dataclass(frozen=True)
class RejectedReadiness:
    attempt_id: str
    attempted_at: datetime
    safe_code: str
    correlation_id: str
    troubleshooting_url: str
    actions_url: str | None
    kind: SetupReadinessKind = SetupReadinessKind.REJECTED


SetupReadiness: TypeAlias = NoScanReadiness | AcceptedReadiness | RejectedReadiness


@dataclass(frozen=True)
class SetupMachineToken:
    id: str
    label: str
    status: SetupTokenStatus
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True)
class SetupLocalRun:
    run_id: str
    display_title: str
    branch: str | None
    commit_sha: str
    dirty: bool
    status: str
    started_at: datetime


class SetupSelectionStatus(StrEnum):
    NONE = "none"
    STALE = "stale"
    SELECTED = "selected"


@dataclass(frozen=True)
class SetupSelection:
    status: SetupSelectionStatus
    requested_repository_id: int | None


@dataclass(frozen=True)
class SignedOutState:
    sign_in_url: str
    kind: SetupStateKind = SetupStateKind.SIGNED_OUT


@dataclass(frozen=True)
class GithubConnectedState:
    identity: SetupGithubIdentity
    install_url: str
    kind: SetupStateKind = SetupStateKind.GITHUB_CONNECTED


@dataclass(frozen=True)
class ApprovalPendingState:
    identity: SetupGithubIdentity
    request_url: str
    kind: SetupStateKind = SetupStateKind.APPROVAL_PENDING


@dataclass(frozen=True)
class InstalledNoRepositoriesState:
    identity: SetupGithubIdentity
    installation: SetupInstallation
    kind: SetupStateKind = SetupStateKind.INSTALLED_NO_REPOSITORIES


@dataclass(frozen=True)
class RepositorySelectionState:
    identity: SetupGithubIdentity
    kind: SetupStateKind = SetupStateKind.REPOSITORY_SELECTION


@dataclass(frozen=True)
class RepositoryReadyState:
    identity: SetupGithubIdentity
    installation: SetupInstallation
    repository: SetupRepository
    capabilities: SetupCapabilities
    actions_readiness: SetupReadiness
    kind: SetupStateKind = SetupStateKind.REPOSITORY_READY


@dataclass(frozen=True)
class RepositoryReadyWriteState:
    identity: SetupGithubIdentity
    installation: SetupInstallation
    repository: SetupRepository
    capabilities: SetupCapabilities
    actions_readiness: SetupReadiness
    kind: SetupStateKind = SetupStateKind.REPOSITORY_READY_WRITE


@dataclass(frozen=True)
class AccessStaleState:
    identity: SetupGithubIdentity
    last_repository: SetupRepository | None = None
    retry_after_seconds: int | None = None
    kind: SetupStateKind = SetupStateKind.ACCESS_STALE


@dataclass(frozen=True)
class InstallationSuspendedState:
    identity: SetupGithubIdentity
    installation: SetupInstallation
    kind: SetupStateKind = SetupStateKind.INSTALLATION_SUSPENDED


SetupState: TypeAlias = (
    SignedOutState
    | GithubConnectedState
    | ApprovalPendingState
    | InstalledNoRepositoriesState
    | RepositorySelectionState
    | RepositoryReadyState
    | RepositoryReadyWriteState
    | AccessStaleState
    | InstallationSuspendedState
)


@dataclass(frozen=True)
class SetupBootstrap:
    version: int
    selection: SetupSelection
    state: SetupState
    installations: tuple[SetupInstallation, ...]
    installations_next_cursor: str | None
    machine_tokens: tuple[SetupMachineToken, ...]
    latest_local_run: SetupLocalRun | None


@dataclass(frozen=True)
class SetupRepositoryPage:
    repositories: tuple[SetupRepository, ...]
    next_cursor: str | None


__all__ = [
    "AccessStaleState",
    "AcceptedReadiness",
    "ApprovalPendingState",
    "GithubConnectedState",
    "InstallationSuspendedState",
    "InstalledNoRepositoriesState",
    "NoScanReadiness",
    "RejectedReadiness",
    "RepositoryReadyState",
    "RepositoryReadyWriteState",
    "RepositorySelectionState",
    "SetupBootstrap",
    "SetupCapabilities",
    "SetupGithubIdentity",
    "SetupInstallation",
    "SetupLocalRun",
    "SetupMachineToken",
    "SetupReadiness",
    "SetupReadinessKind",
    "SetupRepository",
    "SetupRepositoryPage",
    "SetupRepositoryPermission",
    "SetupSelection",
    "SetupSelectionStatus",
    "SetupState",
    "SetupStateKind",
    "SetupTokenStatus",
    "SignedOutState",
]
