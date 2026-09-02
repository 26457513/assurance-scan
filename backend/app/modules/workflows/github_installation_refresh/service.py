"""Coordinate webhook intent with authoritative installation projection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from app.modules.atomic.access.github_repository_reconciliation import (
    GithubInstallationSnapshot,
    GithubRepositoryReconciliationPort,
    ReconciliationResult,
    deactivate_github_installation,
    reconcile_github_repositories,
    suspend_github_installation,
)
from app.modules.atomic.access.github_webhook import GithubWebhookWorkLease


GithubInstallationSnapshotLoader = Callable[[int, datetime], Awaitable[GithubInstallationSnapshot]]
GithubWebhookLeaseGuard = Callable[[], Awaitable[bool]]


class GithubWebhookLeaseLost(RuntimeError):
    """The refresh must not project because another worker owns the delivery."""


async def refresh_github_installation(
    lease: GithubWebhookWorkLease,
    *,
    refreshed_at: datetime,
    snapshot_loader: GithubInstallationSnapshotLoader,
    lease_guard: GithubWebhookLeaseGuard,
    repository: GithubRepositoryReconciliationPort,
) -> ReconciliationResult:
    """Apply deletion intent or a complete API-authoritative installation scope."""
    if lease.event == "installation" and lease.action == "deleted":
        await _require_current_lease(lease_guard)
        return await deactivate_github_installation(
            lease.github_installation_id,
            deleted_at=refreshed_at,
            repository=repository,
        )
    if lease.event == "installation" and lease.action == "suspend":
        await _require_current_lease(lease_guard)
        return await suspend_github_installation(
            lease.github_installation_id,
            suspended_at=refreshed_at,
            verified_at=refreshed_at,
            repository=repository,
        )
    snapshot = await snapshot_loader(lease.github_installation_id, refreshed_at)
    await _require_current_lease(lease_guard)
    return await reconcile_github_repositories(
        snapshot,
        verified_at=refreshed_at,
        repository=repository,
    )


async def _require_current_lease(lease_guard: GithubWebhookLeaseGuard) -> None:
    if not await lease_guard():
        raise GithubWebhookLeaseLost("GitHub webhook work lease was superseded")
