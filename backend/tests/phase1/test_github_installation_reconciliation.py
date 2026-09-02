"""Installation setup-state and authoritative repository reconciliation tests."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.infrastructure.db.models import (
    GithubInstallationRepository,
    Project,
    ProjectMembership,
    User,
)
from app.infrastructure.db.repositories.github_installation_states import (
    SqlAlchemyGithubInstallationStateRepository,
)
from app.infrastructure.db.repositories.github_reconciliation import (
    SqlAlchemyGithubRepositoryReconciliationRepository,
)
from app.infrastructure.db.repositories.identity_sessions import (
    SqlAlchemyBrowserSessionRepository,
)
from app.modules.atomic.access.github_installation_state import (
    GithubInstallationStateValidationError,
    issue_github_installation_state,
)
from app.modules.atomic.access.github_repository_reconciliation import (
    GithubAccountType,
    GithubInstallationSnapshot,
    GithubRepositorySnapshot,
    GithubRepositoryVisibility,
    GithubSelection,
    ReconciliationValidationError,
    reconcile_github_repositories,
)
from app.modules.atomic.access.server_session import issue_browser_session


NOW = dt.datetime(2026, 9, 2, 18, 0, tzinfo=dt.timezone.utc)


class DeterministicRandom:
    def __init__(self) -> None:
        self.offset = 0

    def random_bytes(self, size: int) -> bytes:
        result = bytes((self.offset + index) % 256 for index in range(size))
        self.offset += size
        return result


def _repository(
    repository_id: int,
    name: str,
    *,
    owner_id: int = 26457513,
    archived: bool = False,
) -> GithubRepositorySnapshot:
    return GithubRepositorySnapshot(
        github_repository_id=repository_id,
        github_owner_id=owner_id,
        full_name=f"example-org/{name}",
        default_branch="main",
        visibility=GithubRepositoryVisibility.PRIVATE,
        archived=archived,
        disabled=False,
    )


def _snapshot(*repositories: GithubRepositorySnapshot) -> GithubInstallationSnapshot:
    return GithubInstallationSnapshot(
        github_installation_id=9001,
        github_owner_id=26457513,
        owner_login="example-org",
        account_type=GithubAccountType.ORGANIZATION,
        repository_selection=GithubSelection.SELECTED,
        suspended_at=None,
        deleted_at=None,
        repositories_etag='"repositories-v1"',
        reconciliation_cursor=None,
        repositories=repositories,
    )


@pytest.mark.asyncio
async def test_installation_state_is_independent_bound_and_single_use(session) -> None:
    user = User(email="owner@example.test", role="user", created_at=NOW)
    session.add(user)
    await session.commit()
    issued_session = issue_browser_session(user_id=user.id, now=NOW, random=DeterministicRandom())
    await SqlAlchemyBrowserSessionRepository(session).create(issued_session.record)
    material = issue_github_installation_state(
        browser_session_id=issued_session.record.session_id,
        return_path="/setup",
        now=NOW,
        random=DeterministicRandom(),
    )
    repository = SqlAlchemyGithubInstallationStateRepository(session)
    await repository.create(material)

    wrong_session = await repository.consume(
        material.state,
        browser_session_id="00000000-0000-4000-8000-000000000000",
        now=NOW,
    )
    consumed = await repository.consume(
        material.state,
        browser_session_id=issued_session.record.session_id,
        now=NOW,
    )
    replay = await repository.consume(
        material.state,
        browser_session_id=issued_session.record.session_id,
        now=NOW,
    )

    assert wrong_session is None
    assert consumed is not None and consumed.return_path == "/setup"
    assert replay is None


def test_installation_state_rejects_external_return_paths() -> None:
    with pytest.raises(GithubInstallationStateValidationError, match="allowlisted"):
        issue_github_installation_state(
            browser_session_id="session",
            return_path="https://attacker.example",
            now=NOW,
            random=DeterministicRandom(),
        )


@pytest.mark.asyncio
async def test_reconciliation_creates_by_numeric_identity_and_only_invalidates_drift(session) -> None:
    adapter = SqlAlchemyGithubRepositoryReconciliationRepository(session)
    snapshot = _snapshot(_repository(101, "first"), _repository(102, "second"))

    first = await reconcile_github_repositories(snapshot, verified_at=NOW, repository=adapter)
    projects = (await session.execute(select(Project).order_by(Project.github_repository_id))).scalars().all()
    assert [(row.tag, row.github_repository_id) for row in projects] == [
        ("github-101", 101),
        ("github-102", 102),
    ]
    assert first.enabled_repository_ids == (101, 102)
    assert first.invalidated_project_ids == tuple(row.id for row in projects)

    user = User(email="member@example.test", role="user", created_at=NOW)
    session.add(user)
    await session.flush()
    session.add(
        ProjectMembership(
            user_id=user.id,
            project_id=projects[0].id,
            permission="view",
            source="github_app",
            verified_at=NOW,
            expires_at=NOW + dt.timedelta(minutes=5),
        )
    )
    await session.commit()
    unchanged = await reconcile_github_repositories(
        snapshot,
        verified_at=NOW + dt.timedelta(minutes=1),
        repository=adapter,
    )
    membership = (await session.execute(select(ProjectMembership))).scalar_one()
    assert unchanged.invalidated_project_ids == ()
    assert membership.expires_at == (NOW + dt.timedelta(minutes=5)).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_reconciliation_removal_expires_membership_and_hides_project(session) -> None:
    adapter = SqlAlchemyGithubRepositoryReconciliationRepository(session)
    await reconcile_github_repositories(_snapshot(_repository(101, "first")), verified_at=NOW, repository=adapter)
    project = (await session.execute(select(Project))).scalar_one()
    user = User(email="member@example.test", role="user", created_at=NOW)
    session.add(user)
    await session.flush()
    session.add(
        ProjectMembership(
            user_id=user.id,
            project_id=project.id,
            permission="manage",
            source="github_app",
            verified_at=NOW,
            expires_at=NOW + dt.timedelta(minutes=5),
        )
    )
    await session.commit()

    result = await reconcile_github_repositories(
        _snapshot(),
        verified_at=NOW + dt.timedelta(minutes=1),
        repository=adapter,
    )

    await session.refresh(project)
    membership = (await session.execute(select(ProjectMembership))).scalar_one()
    repository_row = (await session.execute(select(GithubInstallationRepository))).scalar_one()
    assert result.removed_repository_ids == (101,)
    assert result.invalidated_project_ids == (project.id,)
    assert project.hidden is True
    assert repository_row.disabled is True
    assert membership.expires_at == (NOW + dt.timedelta(minutes=1)).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_reconciliation_blocks_installation_owner_identity_change(session) -> None:
    adapter = SqlAlchemyGithubRepositoryReconciliationRepository(session)
    await reconcile_github_repositories(_snapshot(), verified_at=NOW, repository=adapter)
    changed = GithubInstallationSnapshot(
        **{
            **_snapshot().__dict__,
            "github_owner_id": 999,
            "owner_login": "another-owner",
        }
    )

    with pytest.raises(ReconciliationValidationError, match="audited rebind"):
        await reconcile_github_repositories(
            changed,
            verified_at=NOW + dt.timedelta(minutes=1),
            repository=adapter,
        )
