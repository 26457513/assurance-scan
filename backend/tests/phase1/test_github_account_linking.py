"""Explicit immutable GitHub linking and membership projection tests."""

from __future__ import annotations

import datetime as dt
import urllib.parse
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import github_account_link as link_routes
from app.infrastructure.db.connection import get_session
from app.infrastructure.db.models import Base, GithubAccount, Project, ProjectMembership, User
from app.infrastructure.db.repositories.github_account_links import (
    SqlAlchemyGithubAccountLinkRepository,
    SqlAlchemyGithubMembershipProjectionRepository,
)
from app.infrastructure.github_oauth import VerifiedGithubAuthorization
from app.modules.atomic.access.browser_auth import mint_session
from app.modules.atomic.access.github_account_link import (
    GithubIdentityCollisionError,
    LinkGithubAccountCommand,
    UserAlreadyLinkedError,
    link_github_account,
)
from app.modules.atomic.access.github_membership_projection import (
    GithubMembershipProjection,
    GithubProjectPermission,
)
from app.secrets import decrypt


NOW = dt.datetime(2026, 9, 2, 14, 0, tzinfo=dt.timezone.utc)


async def _user(session, email: str) -> User:
    row = User(email=email, role="user", created_at=NOW)
    session.add(row)
    await session.commit()
    return row


def _command(user_id: int, github_user_id: int, login: str = "octocat") -> LinkGithubAccountCommand:
    return LinkGithubAccountCommand(
        user_id=user_id,
        github_user_id=github_user_id,
        login=login,
        user_token="github-user-token",
        refresh_token="github-refresh-token",
        token_expires_at=NOW + dt.timedelta(hours=8),
        verified_at=NOW,
    )


@pytest.mark.asyncio
async def test_link_uses_only_immutable_ids_and_encrypts_credentials(session) -> None:
    user = await _user(session, "existing@example.test")
    repository = SqlAlchemyGithubAccountLinkRepository(session, encryption_key="test-key", key_id="primary")

    await link_github_account(_command(user.id, 12345), linked_at=NOW, repository=repository)

    row = (await session.execute(select(GithubAccount))).scalar_one()
    assert row.user_id == user.id
    assert row.github_user_id == 12345
    assert row.email is None
    assert row.login_at_last_verify == "octocat"
    assert row.encrypted_user_token != "github-user-token"
    assert decrypt(row.encrypted_user_token or "", "test-key") == "github-user-token"


@pytest.mark.asyncio
async def test_link_blocks_github_identity_and_user_collisions(session) -> None:
    first = await _user(session, "first@example.test")
    second = await _user(session, "second@example.test")
    first_id = first.id
    second_id = second.id
    repository = SqlAlchemyGithubAccountLinkRepository(session, encryption_key="test-key", key_id="primary")
    await link_github_account(_command(first_id, 111), linked_at=NOW, repository=repository)

    with pytest.raises(GithubIdentityCollisionError):
        await link_github_account(_command(second_id, 111), linked_at=NOW, repository=repository)
    with pytest.raises(UserAlreadyLinkedError):
        await link_github_account(_command(first_id, 222), linked_at=NOW, repository=repository)


@pytest.mark.asyncio
async def test_projection_replaces_only_github_app_memberships(session) -> None:
    user = await _user(session, "member@example.test")
    first = Project(tag="first", github_repo="org/first", github_repo_key="org/first")
    second = Project(tag="second", github_repo="org/second", github_repo_key="org/second")
    session.add_all([first, second])
    await session.commit()
    user_id = user.id
    first_id = first.id
    second_id = second.id
    session.add(
        ProjectMembership(
            user_id=user_id,
            project_id=first_id,
            permission="manage",
            source="manual",
            verified_at=NOW,
        )
    )
    await session.commit()

    repository = SqlAlchemyGithubMembershipProjectionRepository(session)
    await repository.replace_for_user(
        user_id,
        (
            GithubMembershipProjection(
                project_id=second_id,
                permission=GithubProjectPermission.UPLOAD,
                verified_at=NOW,
                expires_at=NOW + dt.timedelta(minutes=5),
            ),
        ),
    )
    rows = (
        (await session.execute(select(ProjectMembership).where(ProjectMembership.user_id == user_id))).scalars().all()
    )
    assert {(row.project_id, row.source, row.permission) for row in rows} == {
        (first_id, "manual", "manage"),
        (second_id, "github_app", "upload"),
    }

    await repository.replace_for_user(user_id, ())
    remaining = (
        (await session.execute(select(ProjectMembership).where(ProjectMembership.user_id == user_id))).scalars().all()
    )
    assert [(row.project_id, row.source) for row in remaining] == [(first_id, "manual")]


@pytest.mark.asyncio
async def test_http_link_flow_requires_both_existing_session_and_single_use_oauth_proof(tmp_path, monkeypatch) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'link.sqlite'}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def session_override():
        async with sessions() as database_session:
            yield database_session

    settings = SimpleNamespace(
        migration_github_linking_enabled=True,
        github_app_client_id="github-client",
        github_app_client_secret="github-secret",
        token_encryption_key="credential-key",
        public_base_url="https://scan.example.test",
        session_secret="session-secret-at-least-thirty-two-bytes",
    )
    app = FastAPI()
    app.state.settings = settings
    app.include_router(link_routes.router, prefix="/api")
    app.dependency_overrides[get_session] = session_override

    def verified(**_kwargs) -> VerifiedGithubAuthorization:
        return VerifiedGithubAuthorization(
            github_user_id=4242,
            login="verified-login",
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in_seconds=28_800,
        )

    monkeypatch.setattr(link_routes, "exchange_and_verify_github_authorization", verified)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://scan.example.test") as client:
        client.cookies.set(
            "as_session",
            mint_session("existing@example.test", settings.session_secret),
            domain="scan.example.test",
            path="/",
        )
        started = await client.get("/api/v2/github/link/start")
        assert started.status_code == 302
        authorization_query = urllib.parse.parse_qs(urllib.parse.urlsplit(started.headers["location"]).query)
        assert authorization_query["code_challenge_method"] == ["S256"]
        state = authorization_query["state"][0]

        callback = await client.get("/api/v2/github/link/callback", params={"code": "code", "state": state})
        assert callback.status_code == 302
        assert callback.headers["location"] == "/setup?github_link=linked"
        replay = await client.get("/api/v2/github/link/callback", params={"code": "code", "state": state})
        assert replay.status_code == 401

    async with sessions() as database_session:
        account = (await database_session.execute(select(GithubAccount))).scalar_one()
        assert (account.user_id, account.github_user_id, account.email) == (1, 4242, None)
    await engine.dispose()
