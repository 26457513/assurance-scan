"""Durable worker adapter for GitHub installation refresh requests."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.repositories.github_reconciliation import (
    SqlAlchemyGithubRepositoryReconciliationRepository,
)
from app.infrastructure.db.repositories.github_webhooks import (
    SqlAlchemyGithubWebhookDeliveryRepository,
)
from app.infrastructure.github_app_api import (
    GithubAppApiError,
    GithubRateLimitError,
    fetch_authoritative_installation,
)
from app.modules.atomic.access.github_repository_reconciliation import (
    ReconciliationValidationError,
)
from app.modules.atomic.access.github_webhook import (
    complete_github_webhook_work,
    lease_github_webhook_work,
    renew_github_webhook_work,
    retry_github_webhook_work,
)
from app.modules.workflows.github_installation_refresh import (
    GithubInstallationSnapshotLoader,
    GithubWebhookLeaseLost,
    refresh_github_installation,
)


_LOGGER = logging.getLogger(__name__)
_POLL_SECONDS = 2.0


async def process_github_webhook_work_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    snapshot_loader: GithubInstallationSnapshotLoader,
    now: dt.datetime | None = None,
    lease_token_factory: Callable[[], str] | None = None,
) -> bool:
    """Lease and process at most one durable mutation; return whether work existed."""
    def current_time() -> dt.datetime:
        return now or dt.datetime.now(dt.timezone.utc)

    leased_at = current_time()
    token = (lease_token_factory or _lease_token)()
    async with session_factory() as session:
        deliveries = SqlAlchemyGithubWebhookDeliveryRepository(session)
        lease = await lease_github_webhook_work(
            repository=deliveries,
            now=leased_at,
            lease_token=token,
        )
        if lease is None:
            return False

        async def guard_lease() -> bool:
            return await renew_github_webhook_work(
                lease,
                repository=deliveries,
                now=current_time(),
            )

        try:
            await refresh_github_installation(
                lease,
                refreshed_at=leased_at,
                snapshot_loader=snapshot_loader,
                lease_guard=guard_lease,
                repository=SqlAlchemyGithubRepositoryReconciliationRepository(session),
            )
            completed = await complete_github_webhook_work(
                lease,
                repository=deliveries,
                now=current_time(),
            )
            if not completed:
                _LOGGER.warning("GitHub webhook work lease was superseded delivery_id=%s", lease.delivery_id)
        except GithubWebhookLeaseLost:
            _LOGGER.warning("GitHub webhook work projection was fenced delivery_id=%s", lease.delivery_id)
        except GithubRateLimitError as exc:
            await retry_github_webhook_work(
                lease,
                repository=deliveries,
                now=current_time(),
                error_code="github_rate_limited",
                not_before=exc.retry_at,
            )
        except GithubAppApiError:
            await retry_github_webhook_work(
                lease,
                repository=deliveries,
                now=current_time(),
                error_code="github_api_error",
            )
        except ReconciliationValidationError:
            await retry_github_webhook_work(
                lease,
                repository=deliveries,
                now=current_time(),
                error_code="identity_conflict",
            )
        except Exception:
            _LOGGER.error("GitHub webhook work failed delivery_id=%s", lease.delivery_id)
            await retry_github_webhook_work(
                lease,
                repository=deliveries,
                now=current_time(),
                error_code="internal_error",
            )
        return True


async def github_webhook_worker_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    github_app_id: str,
    private_key_pem: bytes,
) -> None:
    """Continuously drain authenticated webhook mutations from durable storage."""

    async def load_snapshot(installation_id: int, refreshed_at: dt.datetime):
        return await asyncio.to_thread(
            fetch_authoritative_installation,
            github_app_id=github_app_id,
            private_key_pem=private_key_pem,
            github_installation_id=installation_id,
            now=refreshed_at,
        )

    while True:
        try:
            processed = await process_github_webhook_work_once(
                session_factory,
                snapshot_loader=load_snapshot,
            )
        except Exception:
            _LOGGER.error("GitHub webhook worker iteration failed")
            processed = False
        if not processed:
            await asyncio.sleep(_POLL_SECONDS)


def _lease_token() -> str:
    return str(uuid.uuid4())


__all__ = ["github_webhook_worker_loop", "process_github_webhook_work_once"]
