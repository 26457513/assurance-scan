"""Orchestrate one coherent Setup bootstrap without framework coupling."""

from __future__ import annotations

from datetime import datetime

from app.modules.atomic.access.setup_state import validate_repository_page, validate_setup_bootstrap
from app.modules.atomic.access.setup_state.models import (
    AccessStaleState,
    ApprovalPendingState,
    GithubConnectedState,
    InstallationSuspendedState,
    InstalledNoRepositoriesState,
    RepositoryReadyState,
    RepositoryReadyWriteState,
    RepositorySelectionState,
    SetupBootstrap,
    SetupCapabilities,
    SetupRepositoryPage,
    SetupRepositoryPermission,
    SetupSelection,
    SetupSelectionStatus,
    SetupState,
    SignedOutState,
)

from .models import SetupLinks
from .ports import SetupProjectionRepositoryPort


async def setup_bootstrap(
    *,
    user_id: int | None,
    selected_repository_id: int | None,
    installations_cursor: str | None,
    now: datetime,
    repository: SetupProjectionRepositoryPort,
    links: SetupLinks,
) -> SetupBootstrap:
    if user_id is None:
        return validate_setup_bootstrap(
            SetupBootstrap(
                version=2,
                selection=SetupSelection(SetupSelectionStatus.NONE, None),
                state=SignedOutState(sign_in_url=links.sign_in_url),
                installations=(),
                installations_next_cursor=None,
                machine_tokens=(),
                latest_local_run=None,
            )
        )
    material = await repository.load_bootstrap(
        user_id=user_id,
        selected_repository_id=selected_repository_id,
        installations_cursor=installations_cursor,
        now=now,
    )
    identity = material.identity
    state: SetupState
    if identity is None:
        state = SignedOutState(sign_in_url=links.sign_in_url)
    elif material.approval_request_url is not None:
        state = ApprovalPendingState(identity=identity, request_url=material.approval_request_url)
    elif material.suspended_installation is not None:
        suspended_installation = material.suspended_installation
        state = InstallationSuspendedState(
            identity=identity,
            installation=suspended_installation,
        )
    elif material.access_stale:
        state = AccessStaleState(
            identity=identity,
            last_repository=material.last_repository or material.selected_repository,
            retry_after_seconds=material.retry_after_seconds,
        )
    elif not material.installations:
        state = GithubConnectedState(identity=identity, install_url=links.install_url)
    elif material.selected_repository is None:
        empty_installation = next(
            (installation for installation in material.installations if installation.enabled_repository_count == 0),
            None,
        )
        if empty_installation is not None and len(material.installations) == 1:
            state = InstalledNoRepositoriesState(
                identity=identity,
                installation=empty_installation,
            )
        else:
            state = RepositorySelectionState(identity=identity)
    else:
        selected = material.selected_repository
        installation = material.selected_installation
        if installation is None:
            raise RuntimeError("selected Setup repository has no installation")
        can_write = selected.permission in {
            SetupRepositoryPermission.WRITE,
            SetupRepositoryPermission.MAINTAIN,
            SetupRepositoryPermission.ADMIN,
        }
        capabilities = SetupCapabilities(
            can_local_scan=can_write,
            can_manage=selected.permission is SetupRepositoryPermission.ADMIN,
        )
        state_type = RepositoryReadyWriteState if can_write else RepositoryReadyState
        state = state_type(
            identity=identity,
            installation=installation,
            repository=selected,
            capabilities=capabilities,
            actions_readiness=material.actions_readiness,
        )
    repository_is_active = isinstance(state, (RepositoryReadyState, RepositoryReadyWriteState))
    return validate_setup_bootstrap(
        SetupBootstrap(
            version=2,
            selection=(
                SetupSelection(SetupSelectionStatus.NONE, None)
                if selected_repository_id is None
                else SetupSelection(
                    SetupSelectionStatus.SELECTED if repository_is_active else SetupSelectionStatus.STALE,
                    selected_repository_id,
                )
            ),
            state=state,
            installations=material.installations,
            installations_next_cursor=material.installations_next_cursor,
            machine_tokens=() if isinstance(state, SignedOutState) else material.machine_tokens,
            latest_local_run=(
                material.latest_local_run
                if repository_is_active
                else None
            ),
        )
    )


async def setup_repositories(
    *,
    user_id: int,
    github_installation_id: int,
    query: str,
    cursor: str | None,
    limit: int,
    now: datetime,
    repository: SetupProjectionRepositoryPort,
) -> SetupRepositoryPage:
    if github_installation_id <= 0:
        raise ValueError("GitHub installation ID must be positive")
    if not 1 <= limit <= 50:
        raise ValueError("repository page limit must be between 1 and 50")
    if len(query) > 128 or any(ord(character) < 32 for character in query):
        raise ValueError("repository search query is invalid")
    page = await repository.search_repositories(
        user_id=user_id,
        github_installation_id=github_installation_id,
        query=query,
        cursor=cursor,
        limit=limit,
        now=now,
    )
    return validate_repository_page(page)


__all__ = ["setup_bootstrap", "setup_repositories"]
