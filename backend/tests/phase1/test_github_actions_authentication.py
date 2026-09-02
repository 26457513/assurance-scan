"""Live repository authorization for authenticated GitHub Actions uploads."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import Base, GithubAppInstallation, Project
from app.infrastructure.db.repositories.github_oidc_replays import (
    SqlAlchemyGithubOidcReplayRepository,
)
from app.infrastructure.db.repositories.github_reconciliation import (
    SqlAlchemyGithubRepositoryReconciliationRepository,
)
from app.infrastructure.db.repositories.github_upload_authorization import (
    SqlAlchemyGithubUploadAuthorizationRepository,
)
from app.modules.atomic.access.github_oidc import GithubOidcClaims, OidcValidationError
from app.modules.atomic.access.github_repository_reconciliation import (
    GithubAccountType,
    GithubInstallationSnapshot,
    GithubRepositorySnapshot,
    GithubRepositoryVisibility,
    GithubSelection,
    reconcile_github_repositories,
)
from app.modules.workflows.github_actions_authentication import (
    authorize_github_actions_upload,
)


NOW = dt.datetime(2026, 9, 2, 12, tzinfo=dt.timezone.utc)


def _repository(*, default_branch: str = "main") -> GithubRepositorySnapshot:
    return GithubRepositorySnapshot(
        github_repository_id=424242,
        github_owner_id=26457513,
        full_name="example-org/example-repo",
        default_branch=default_branch,
        visibility=GithubRepositoryVisibility.PRIVATE,
        archived=False,
        disabled=False,
    )


def _installation() -> GithubInstallationSnapshot:
    return GithubInstallationSnapshot(
        github_installation_id=9001,
        github_owner_id=26457513,
        owner_login="example-org",
        account_type=GithubAccountType.ORGANIZATION,
        repository_selection=GithubSelection.SELECTED,
        suspended_at=None,
        deleted_at=None,
        repositories_etag=None,
        reconciliation_cursor=None,
        repositories=(_repository(),),
    )


def _claims() -> GithubOidcClaims:
    return GithubOidcClaims(
        subject="repo:example-org/example-repo:ref:refs/heads/main",
        repository_id=424242,
        repository_owner_id=26457513,
        repository="example-org/example-repo",
        run_id=123456789,
        run_number=26,
        run_attempt=1,
        sha="a" * 40,
        ref="refs/heads/main",
        event_name="push",
        actor="octocat",
        actor_id=583231,
        workflow_ref="example-org/example-repo/.github/workflows/assurance-scan.yml@refs/heads/main",
        workflow_sha="a" * 40,
        issued_at=NOW - dt.timedelta(minutes=1),
        not_before=NOW - dt.timedelta(minutes=1),
        expires_at=NOW + dt.timedelta(minutes=9),
        jti="f87d8b0c-29f8-4c11-8cc0-3eb13482b386",
    )


async def _database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'github-upload.sqlite'}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        await reconcile_github_repositories(
            _installation(),
            verified_at=NOW - dt.timedelta(minutes=10),
            repository=SqlAlchemyGithubRepositoryReconciliationRepository(session),
        )
    return engine, sessions


@pytest.mark.asyncio
async def test_live_repository_state_authorizes_and_refreshes_project(tmp_path) -> None:
    engine, sessions = await _database(tmp_path)
    calls: list[tuple[int, str]] = []

    async def load(installation_id: int, full_name: str, _now: dt.datetime):
        calls.append((installation_id, full_name))
        return _repository()

    async with sessions() as session:
        principal = await authorize_github_actions_upload(
            _claims(),
            now=NOW,
            repository_loader=load,
            authorization_repository=SqlAlchemyGithubUploadAuthorizationRepository(session),
            replay_repository=SqlAlchemyGithubOidcReplayRepository(session),
        )
    assert principal.project_id == 1
    assert calls == [(9001, "example-org/example-repo")]
    async with sessions() as session:
        project = (await session.execute(select(Project))).scalar_one()
        assert project.default_scan_ref == "refs/heads/main"
    await engine.dispose()


@pytest.mark.asyncio
async def test_uninstalled_repository_fails_before_github_request(tmp_path) -> None:
    engine, sessions = await _database(tmp_path)
    claims = replace(_claims(), repository_id=999999)

    async def forbidden(*_args):
        raise AssertionError("uninstalled repositories must not mint installation tokens")

    async with sessions() as session:
        with pytest.raises(OidcValidationError, match="repository_not_authorized"):
            await authorize_github_actions_upload(
                claims,
                now=NOW,
                repository_loader=forbidden,
                authorization_repository=SqlAlchemyGithubUploadAuthorizationRepository(session),
                replay_repository=SqlAlchemyGithubOidcReplayRepository(session),
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_scope_change_during_github_request_fails_closed(tmp_path) -> None:
    engine, sessions = await _database(tmp_path)

    async def suspend(_installation_id: int, _full_name: str, _now: dt.datetime):
        async with sessions() as other:
            await other.execute(
                update(GithubAppInstallation)
                .where(GithubAppInstallation.github_installation_id == 9001)
                .values(suspended_at=NOW)
            )
            await other.commit()
        return _repository()

    async with sessions() as session:
        with pytest.raises(OidcValidationError, match="stale_entitlement"):
            await authorize_github_actions_upload(
                _claims(),
                now=NOW,
                repository_loader=suspend,
                authorization_repository=SqlAlchemyGithubUploadAuthorizationRepository(session),
                replay_repository=SqlAlchemyGithubOidcReplayRepository(session),
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_default_branch_is_taken_from_live_github_response(tmp_path) -> None:
    engine, sessions = await _database(tmp_path)

    async def renamed_default(_installation_id: int, _full_name: str, _now: dt.datetime):
        return _repository(default_branch="develop")

    async with sessions() as session:
        with pytest.raises(OidcValidationError, match="non_default_branch"):
            await authorize_github_actions_upload(
                _claims(),
                now=NOW,
                repository_loader=renamed_default,
                authorization_repository=SqlAlchemyGithubUploadAuthorizationRepository(session),
                replay_repository=SqlAlchemyGithubOidcReplayRepository(session),
            )
    await engine.dispose()
