"""Validation and wire serialization for Setup state."""

from __future__ import annotations

import dataclasses
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .models import (
    AccessStaleState,
    AcceptedReadiness,
    GithubConnectedState,
    InstallationSuspendedState,
    InstalledNoRepositoriesState,
    NoScanReadiness,
    RejectedReadiness,
    RepositoryReadyState,
    RepositoryReadyWriteState,
    RepositorySelectionState,
    SetupBootstrap,
    SetupReadiness,
    SetupRepository,
    SetupRepositoryPage,
    SetupSelectionStatus,
    SignedOutState,
)


_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9.-]+/[A-Za-z0-9_.-]+$")


def validate_setup_bootstrap(value: SetupBootstrap) -> SetupBootstrap:
    if value.version != 2:
        raise ValueError("Setup bootstrap version must be 2")
    if value.selection.status is SetupSelectionStatus.NONE:
        if value.selection.requested_repository_id is not None:
            raise ValueError("empty Setup selection cannot have a repository")
    elif value.selection.requested_repository_id is None or value.selection.requested_repository_id <= 0:
        raise ValueError("Setup selection requires a positive repository identity")
    _validate_installations(value.installations)
    _validate_state(value)
    for token in value.machine_tokens:
        if not token.id or not token.label:
            raise ValueError("Setup token identity is incomplete")
        _aware(token.created_at)
        _aware(token.expires_at)
        if token.last_used_at is not None:
            _aware(token.last_used_at)
    if value.latest_local_run is not None:
        local = value.latest_local_run
        if not local.display_title or not local.run_id or not _SHA.fullmatch(local.commit_sha):
            raise ValueError("latest local run identity is invalid")
        if local.status not in {"queued", "running", "completed", "failed", "cancelled"}:
            raise ValueError("latest local run status is invalid")
        _aware(local.started_at)
    readiness = getattr(value.state, "actions_readiness", None)
    if readiness is not None:
        validate_readiness(readiness)
    repository = getattr(value.state, "repository", None)
    if repository is not None:
        validate_repository(repository)
        if (
            value.selection.status is not SetupSelectionStatus.SELECTED
            or value.selection.requested_repository_id != repository.github_repository_id
        ):
            raise ValueError("active Setup repository must match the selection")
    elif value.selection.status is SetupSelectionStatus.SELECTED:
        raise ValueError("selected Setup state requires an active repository")
    if value.latest_local_run is not None and value.selection.status is not SetupSelectionStatus.SELECTED:
        raise ValueError("local run summary requires an active repository")
    if isinstance(value.state, SignedOutState) and (value.installations or value.machine_tokens):
        raise ValueError("signed-out Setup cannot contain account data")
    return value


def validate_repository_page(value: SetupRepositoryPage) -> SetupRepositoryPage:
    seen: set[int] = set()
    for repository in value.repositories:
        validate_repository(repository)
        if repository.github_repository_id in seen:
            raise ValueError("Setup repository page contains a duplicate")
        seen.add(repository.github_repository_id)
    return value


def validate_repository(repository: SetupRepository) -> SetupRepository:
    if min(
        repository.github_repository_id,
        repository.github_installation_id,
        repository.project_id,
    ) <= 0:
        raise ValueError("Setup repository identities must be positive")
    if not _REPOSITORY.fullmatch(repository.full_name):
        raise ValueError("Setup repository full name is invalid")
    if not repository.default_branch.strip():
        raise ValueError("Setup repository default branch is required")
    return repository


def validate_readiness(value: SetupReadiness) -> SetupReadiness:
    if isinstance(value, NoScanReadiness):
        return value
    if isinstance(value, AcceptedReadiness):
        _aware(value.accepted_at)
        if not value.attempt_id or not value.run_id or not value.actions_url:
            raise ValueError("accepted readiness is incomplete")
        return value
    if not isinstance(value, RejectedReadiness):
        raise TypeError("unsupported Setup readiness")
    _aware(value.attempted_at)
    if not value.attempt_id or not _SAFE_CODE.fullmatch(value.safe_code) or not value.correlation_id:
        raise ValueError("rejected readiness requires safe failure evidence")
    return value


def setup_payload(value: SetupBootstrap) -> dict[str, Any]:
    """Serialize GitHub IDs as decimal strings for JavaScript-safe transport."""
    validate_setup_bootstrap(value)
    return _wire(dataclasses.asdict(value))


def repository_page_payload(value: SetupRepositoryPage) -> dict[str, Any]:
    validate_repository_page(value)
    return _wire(dataclasses.asdict(value))


def _validate_installations(installations: tuple[Any, ...]) -> None:
    seen: set[int] = set()
    for installation in installations:
        if installation.github_installation_id <= 0 or installation.github_owner_id <= 0:
            raise ValueError("Setup installation identities must be positive")
        if installation.github_installation_id in seen:
            raise ValueError("Setup installations must be unique")
        if installation.enabled_repository_count < 0 or not installation.owner_login or not installation.manage_url:
            raise ValueError("Setup installation summary is invalid")
        if installation.account_type not in {"User", "Organization"}:
            raise ValueError("Setup installation account type is invalid")
        if installation.repository_selection not in {"all", "selected"}:
            raise ValueError("Setup installation selection is invalid")
        expected_manage_url = (
            "https://github.com/settings/installations/"
            f"{installation.github_installation_id}"
        )
        if installation.manage_url != expected_manage_url:
            raise ValueError("Setup installation management URL is invalid")
        seen.add(installation.github_installation_id)


def _validate_state(value: SetupBootstrap) -> None:
    state = value.state
    identity = getattr(state, "identity", None)
    if identity is not None and (identity.github_user_id <= 0 or not identity.login):
        raise ValueError("Setup GitHub identity is invalid")
    if isinstance(state, SignedOutState):
        if value.selection.status is not SetupSelectionStatus.NONE or not state.sign_in_url:
            raise ValueError("signed-out Setup state is invalid")
        return
    if isinstance(state, GithubConnectedState):
        if not state.install_url:
            raise ValueError("GitHub-connected Setup state needs an installation URL")
        return
    if isinstance(state, RepositorySelectionState):
        return
    installation = getattr(state, "installation", None)
    if installation is not None:
        _validate_installations((installation,))
    if isinstance(state, InstalledNoRepositoriesState):
        if state.installation.enabled_repository_count != 0:
            raise ValueError("empty-installation Setup state has repositories")
        return
    if isinstance(state, InstallationSuspendedState):
        return
    if isinstance(state, AccessStaleState):
        if state.retry_after_seconds is not None and state.retry_after_seconds < 0:
            raise ValueError("Setup retry delay cannot be negative")
        if state.last_repository is not None:
            validate_repository(state.last_repository)
        return
    if isinstance(state, (RepositoryReadyState, RepositoryReadyWriteState)):
        if state.repository.github_installation_id != state.installation.github_installation_id:
            raise ValueError("Setup repository and installation do not match")
        can_write = state.repository.permission.value in {"write", "maintain", "admin"}
        if state.capabilities.can_local_scan != can_write:
            raise ValueError("Setup local-scan capability does not match permission")
        if state.capabilities.can_manage != (state.repository.permission.value == "admin"):
            raise ValueError("Setup management capability does not match permission")


def _wire(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {item_key: _wire(item, item_key) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _aware(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, int) and key is not None and (
        (key.startswith("github_") and key.endswith("_id")) or key == "requested_repository_id"
    ):
        return str(value)
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Setup timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "repository_page_payload",
    "setup_payload",
    "validate_readiness",
    "validate_repository",
    "validate_repository_page",
    "validate_setup_bootstrap",
]
