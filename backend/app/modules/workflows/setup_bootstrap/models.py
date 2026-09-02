"""Application-layer inputs and projection material for Setup."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.atomic.access.setup_state.models import (
    SetupGithubIdentity,
    SetupInstallation,
    SetupLocalRun,
    SetupMachineToken,
    SetupReadiness,
    SetupRepository,
)


@dataclass(frozen=True)
class SetupLinks:
    sign_in_url: str
    install_url: str


@dataclass(frozen=True)
class SetupProjectionMaterial:
    identity: SetupGithubIdentity | None
    installations: tuple[SetupInstallation, ...]
    installations_next_cursor: str | None
    selected_repository: SetupRepository | None
    selected_installation: SetupInstallation | None
    suspended_installation: SetupInstallation | None
    last_repository: SetupRepository | None
    access_stale: bool
    retry_after_seconds: int | None
    approval_request_url: str | None
    actions_readiness: SetupReadiness
    machine_tokens: tuple[SetupMachineToken, ...]
    latest_local_run: SetupLocalRun | None


__all__ = ["SetupLinks", "SetupProjectionMaterial"]
