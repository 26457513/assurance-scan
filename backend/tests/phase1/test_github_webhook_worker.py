"""Authoritative GitHub webhook refresh worker integration tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import (
    Base,
    GithubAppInstallation,
    GithubInstallationRepository,
    GithubWebhookDelivery,
    Project,
)
from app.infrastructure.db.repositories.github_reconciliation import (
    SqlAlchemyGithubRepositoryReconciliationRepository,
)
from app.infrastructure.db.repositories.github_webhooks import (
    SqlAlchemyGithubWebhookDeliveryRepository,
)
from app.infrastructure.github_app_api import GithubAppApiError
from app.infrastructure.github_app_api import GithubAppInstallationState
from app.infrastructure.github_reconciliation_scheduler import reconcile_due_github_installations
from app.infrastructure.github_webhook_worker import process_github_webhook_work_once
from app.modules.atomic.access.github_repository_reconciliation import (
    GithubAccountType,
    GithubInstallationSnapshot,
    GithubRepositorySnapshot,
    GithubRepositoryVisibility,
    GithubSelection,
    reconcile_github_repositories,
)
from app.modules.atomic.access.github_webhook import (
    GithubWebhookSecrets,
    claim_github_webhook,
    verify_github_webhook,
)


NOW = dt.datetime(2026, 9, 2, 22, 0, tzinfo=dt.timezone.utc)
SECRET = b"assurance-scan-current-test-secret"


def _snapshot() -> GithubInstallationSnapshot:
    return GithubInstallationSnapshot(
        github_installation_id=9001,
        github_owner_id=26457513,
        owner_login="example-org",
        account_type=GithubAccountType.ORGANIZATION,
        repository_selection=GithubSelection.SELECTED,
        suspended_at=None,
        deleted_at=None,
        repositories_etag='"v1"',
        reconciliation_cursor=None,
        repositories=(
            GithubRepositorySnapshot(
                github_repository_id=424242,
                github_owner_id=26457513,
                full_name="example-org/example-repo",
                default_branch="main",
                visibility=GithubRepositoryVisibility.PRIVATE,
                archived=False,
                disabled=False,
            ),
        ),
    )


def _verified(action: str):
    body = f'{{"action":"{action}","installation":{{"id":9001}}}}'.encode()
    signature = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    return verify_github_webhook(
        body,
        content_type="application/json",
        delivery_id="f87d8b0c-29f8-4c11-8cc0-3eb13482b386",
        event="installation",
        signature=signature,
        secrets=GithubWebhookSecrets(current=SECRET),
        now=NOW,
    )


async def _database(tmp_path, name: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_worker_refreshes_authoritative_scope_and_completes_delivery(tmp_path) -> None:
    engine, sessions = await _database(tmp_path, "refresh.sqlite")
    async with sessions() as session:
        await claim_github_webhook(
            _verified("created"),
            repository=SqlAlchemyGithubWebhookDeliveryRepository(session),
            now=NOW,
        )

    async def load_snapshot(installation_id: int, refreshed_at: dt.datetime):
        assert installation_id == 9001
        assert refreshed_at == NOW
        return _snapshot()

    assert await process_github_webhook_work_once(
        sessions,
        snapshot_loader=load_snapshot,
        now=NOW,
        lease_token_factory=lambda: "d8cf87fd-0489-4a4f-8d55-8bf7f5ff9244",
    )
    async with sessions() as session:
        delivery = (await session.execute(select(GithubWebhookDelivery))).scalar_one()
        project = (await session.execute(select(Project))).scalar_one()
        assert delivery.status == "processed"
        assert delivery.attempt_count == 1
        assert project.github_repository_id == 424242
        assert project.hidden is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_deleted_installation_disables_scope_without_calling_snapshot_loader(tmp_path) -> None:
    engine, sessions = await _database(tmp_path, "deleted.sqlite")
    async with sessions() as session:
        await reconcile_github_repositories(
            _snapshot(),
            verified_at=NOW - dt.timedelta(minutes=1),
            repository=SqlAlchemyGithubRepositoryReconciliationRepository(session),
        )
        await claim_github_webhook(
            _verified("deleted"),
            repository=SqlAlchemyGithubWebhookDeliveryRepository(session),
            now=NOW,
        )

    async def forbidden_loader(_installation_id: int, _refreshed_at: dt.datetime):
        raise AssertionError("deleted installations must not be fetched by display metadata")

    assert await process_github_webhook_work_once(
        sessions,
        snapshot_loader=forbidden_loader,
        now=NOW,
        lease_token_factory=lambda: "d8cf87fd-0489-4a4f-8d55-8bf7f5ff9244",
    )
    async with sessions() as session:
        installation = (await session.execute(select(GithubAppInstallation))).scalar_one()
        repository = (await session.execute(select(GithubInstallationRepository))).scalar_one()
        project = (await session.execute(select(Project))).scalar_one()
        delivery = (await session.execute(select(GithubWebhookDelivery))).scalar_one()
        assert installation.deleted_at == NOW.replace(tzinfo=None)
        assert repository.disabled is True
        assert repository.removed_at == NOW.replace(tzinfo=None)
        assert project.hidden is True
        assert delivery.status == "processed"
    await engine.dispose()


@pytest.mark.asyncio
async def test_suspended_installation_disables_but_preserves_repository_scope(tmp_path) -> None:
    engine, sessions = await _database(tmp_path, "suspended.sqlite")
    async with sessions() as session:
        await reconcile_github_repositories(
            _snapshot(),
            verified_at=NOW - dt.timedelta(minutes=1),
            repository=SqlAlchemyGithubRepositoryReconciliationRepository(session),
        )
        await claim_github_webhook(
            _verified("suspend"),
            repository=SqlAlchemyGithubWebhookDeliveryRepository(session),
            now=NOW,
        )

    async def forbidden_loader(_installation_id: int, _refreshed_at: dt.datetime):
        raise AssertionError("suspended installations must be disabled without minting a token")

    assert await process_github_webhook_work_once(
        sessions,
        snapshot_loader=forbidden_loader,
        now=NOW,
        lease_token_factory=lambda: "d8cf87fd-0489-4a4f-8d55-8bf7f5ff9244",
    )
    async with sessions() as session:
        installation = (await session.execute(select(GithubAppInstallation))).scalar_one()
        repository = (await session.execute(select(GithubInstallationRepository))).scalar_one()
        project = (await session.execute(select(Project))).scalar_one()
        assert installation.suspended_at == NOW.replace(tzinfo=None)
        assert repository.disabled is True
        assert repository.removed_at is None
        assert project.hidden is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_github_failure_releases_delivery_with_bounded_retry(tmp_path) -> None:
    engine, sessions = await _database(tmp_path, "retry.sqlite")
    async with sessions() as session:
        await claim_github_webhook(
            _verified("created"),
            repository=SqlAlchemyGithubWebhookDeliveryRepository(session),
            now=NOW,
        )

    async def unavailable(_installation_id: int, _refreshed_at: dt.datetime):
        raise GithubAppApiError("unavailable")

    assert await process_github_webhook_work_once(
        sessions,
        snapshot_loader=unavailable,
        now=NOW,
        lease_token_factory=lambda: "d8cf87fd-0489-4a4f-8d55-8bf7f5ff9244",
    )
    async with sessions() as session:
        delivery = (await session.execute(select(GithubWebhookDelivery))).scalar_one()
        assert delivery.status == "received"
        assert delivery.attempt_count == 1
        assert delivery.last_error_code == "github_api_error"
        assert delivery.available_at == (NOW + dt.timedelta(seconds=30)).replace(tzinfo=None)
        assert delivery.lease_token is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_lease_is_fenced_before_authoritative_projection(tmp_path) -> None:
    engine, sessions = await _database(tmp_path, "fenced.sqlite")
    async with sessions() as session:
        await claim_github_webhook(
            _verified("created"),
            repository=SqlAlchemyGithubWebhookDeliveryRepository(session),
            now=NOW,
        )

    async def expire_before_projection(_installation_id: int, _refreshed_at: dt.datetime):
        async with sessions() as competing_session:
            await competing_session.execute(
                update(GithubWebhookDelivery).values(lease_expires_at=NOW - dt.timedelta(seconds=1))
            )
            await competing_session.commit()
        return _snapshot()

    assert await process_github_webhook_work_once(
        sessions,
        snapshot_loader=expire_before_projection,
        now=NOW,
        lease_token_factory=lambda: "d8cf87fd-0489-4a4f-8d55-8bf7f5ff9244",
    )
    async with sessions() as session:
        delivery = (await session.execute(select(GithubWebhookDelivery))).scalar_one()
        projects = (await session.execute(select(Project))).scalars().all()
        assert delivery.status == "received"
        assert delivery.attempt_count == 1
        assert projects == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_scheduled_repair_refreshes_suspends_and_deletes_only_due_installations(tmp_path) -> None:
    engine, sessions = await _database(tmp_path, "scheduled.sqlite")
    old = NOW - dt.timedelta(hours=7)
    async with sessions() as session:
        await reconcile_github_repositories(
            _snapshot(),
            verified_at=old,
            repository=SqlAlchemyGithubRepositoryReconciliationRepository(session),
        )
        session.add_all(
            [
                _installation(9002, last_reconciled_at=old),
                _installation(9003, last_reconciled_at=old),
                _installation(9004, last_reconciled_at=NOW),
            ]
        )
        await session.commit()

    async def load_states(_checked_at: dt.datetime):
        return (
            GithubAppInstallationState(9001, None),
            GithubAppInstallationState(9002, NOW - dt.timedelta(hours=1)),
        )

    async def load_installation(installation_id: int, _checked_at: dt.datetime):
        assert installation_id == 9001
        return _snapshot()

    result = await reconcile_due_github_installations(
        sessions,
        states_loader=load_states,
        installation_loader=load_installation,
        now=NOW,
    )

    assert result.due == 3
    assert result.refreshed == 1
    assert result.suspended == 1
    assert result.deleted == 1
    assert result.failed == 0
    async with sessions() as session:
        installations = {
            row.github_installation_id: row
            for row in (await session.execute(select(GithubAppInstallation))).scalars()
        }
        assert installations[9001].last_reconciled_at == NOW.replace(tzinfo=None)
        assert installations[9002].suspended_at == (NOW - dt.timedelta(hours=1)).replace(tzinfo=None)
        assert installations[9002].deleted_at is None
        assert installations[9003].deleted_at == NOW.replace(tzinfo=None)
        assert installations[9004].deleted_at is None
    await engine.dispose()


def _installation(
    github_installation_id: int,
    *,
    last_reconciled_at: dt.datetime,
) -> GithubAppInstallation:
    return GithubAppInstallation(
        github_installation_id=github_installation_id,
        github_owner_id=github_installation_id + 1000,
        owner_login_at_last_verify=f"owner-{github_installation_id}",
        account_type="organization",
        repository_selection="selected",
        suspended_at=None,
        deleted_at=None,
        repositories_etag=None,
        reconciliation_cursor=None,
        last_reconciled_at=last_reconciled_at,
        created_at=last_reconciled_at,
        updated_at=last_reconciled_at,
    )
