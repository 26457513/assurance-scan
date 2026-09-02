"""Six-hour repair scheduler for GitHub installation and repository scope."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.models import GithubAppInstallation
from app.infrastructure.db.repositories.github_reconciliation import (
    SqlAlchemyGithubRepositoryReconciliationRepository,
    load_github_installation_repository_cache,
)
from app.infrastructure.github_app_api import (
    GithubAppApiError,
    GithubAppInstallationState,
    GithubRateLimitError,
    fetch_authoritative_installation,
    fetch_github_app_installation_states,
)
from app.modules.atomic.access.github_repository_reconciliation import (
    GithubInstallationSnapshot,
    ReconciliationValidationError,
    deactivate_github_installation,
    reconcile_github_repositories,
    suspend_github_installation,
)


GithubAppStatesLoader = Callable[[dt.datetime], Awaitable[tuple[GithubAppInstallationState, ...]]]
GithubInstallationLoader = Callable[[int, dt.datetime], Awaitable[GithubInstallationSnapshot]]
_LOGGER = logging.getLogger(__name__)
_REPAIR_INTERVAL = dt.timedelta(hours=6)


@dataclass(frozen=True)
class GithubReconciliationRunResult:
    due: int
    refreshed: int
    suspended: int
    deleted: int
    failed: int


async def reconcile_due_github_installations(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    states_loader: GithubAppStatesLoader,
    installation_loader: GithubInstallationLoader,
    now: dt.datetime | None = None,
) -> GithubReconciliationRunResult:
    """Repair every installation whose last complete check is at least six hours old."""
    checked_at = now or dt.datetime.now(dt.timezone.utc)
    cutoff = checked_at - _REPAIR_INTERVAL
    async with session_factory() as session:
        due_ids = tuple(
            (
                await session.execute(
                    select(GithubAppInstallation.github_installation_id)
                    .where(
                        GithubAppInstallation.deleted_at.is_(None),
                        or_(
                            GithubAppInstallation.last_reconciled_at.is_(None),
                            GithubAppInstallation.last_reconciled_at <= cutoff,
                        ),
                    )
                    .order_by(GithubAppInstallation.github_installation_id)
                )
            ).scalars()
        )
    if not due_ids:
        return GithubReconciliationRunResult(due=0, refreshed=0, suspended=0, deleted=0, failed=0)
    states = {state.github_installation_id: state for state in await states_loader(checked_at)}
    refreshed = suspended = deleted = failed = 0
    for installation_id in due_ids:
        try:
            async with session_factory() as session:
                repository = SqlAlchemyGithubRepositoryReconciliationRepository(session)
                state = states.get(installation_id)
                if state is None:
                    await deactivate_github_installation(
                        installation_id,
                        deleted_at=checked_at,
                        repository=repository,
                    )
                    deleted += 1
                elif state.suspended_at is not None:
                    await suspend_github_installation(
                        installation_id,
                        suspended_at=state.suspended_at,
                        verified_at=checked_at,
                        repository=repository,
                    )
                    suspended += 1
                else:
                    snapshot = await installation_loader(installation_id, checked_at)
                    await reconcile_github_repositories(
                        snapshot,
                        verified_at=checked_at,
                        repository=repository,
                    )
                    refreshed += 1
        except GithubRateLimitError:
            failed += 1
            break
        except (GithubAppApiError, ReconciliationValidationError):
            failed += 1
    return GithubReconciliationRunResult(
        due=len(due_ids),
        refreshed=refreshed,
        suspended=suspended,
        deleted=deleted,
        failed=failed,
    )


async def github_reconciliation_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    github_app_id: str,
    private_key_pem: bytes,
) -> None:
    """Run complete App reconciliation immediately and every six hours."""

    async def load_states(checked_at: dt.datetime) -> tuple[GithubAppInstallationState, ...]:
        return await asyncio.to_thread(
            fetch_github_app_installation_states,
            github_app_id=github_app_id,
            private_key_pem=private_key_pem,
            now=checked_at,
        )

    async def load_installation(
        installation_id: int,
        checked_at: dt.datetime,
    ) -> GithubInstallationSnapshot:
        async with session_factory() as session:
            cache = await load_github_installation_repository_cache(
                session,
                installation_id,
            )
        return await asyncio.to_thread(
            fetch_authoritative_installation,
            github_app_id=github_app_id,
            private_key_pem=private_key_pem,
            github_installation_id=installation_id,
            now=checked_at,
            repositories_etag=cache.repositories_etag,
            cached_repositories=(
                cache.repositories if cache.repositories_etag is not None else None
            ),
        )

    while True:
        try:
            result = await reconcile_due_github_installations(
                session_factory,
                states_loader=load_states,
                installation_loader=load_installation,
            )
            _LOGGER.info(
                "GitHub reconciliation completed due=%d refreshed=%d suspended=%d deleted=%d failed=%d",
                result.due,
                result.refreshed,
                result.suspended,
                result.deleted,
                result.failed,
            )
        except Exception:
            _LOGGER.error("GitHub reconciliation iteration failed")
        await asyncio.sleep(_REPAIR_INTERVAL.total_seconds())


__all__ = [
    "GithubReconciliationRunResult",
    "github_reconciliation_loop",
    "reconcile_due_github_installations",
]
