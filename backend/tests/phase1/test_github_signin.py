"""Clean-launch GitHub sign-in security and HTTP contract tests."""

from __future__ import annotations

import datetime as dt
import urllib.parse
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import github_auth
from app.infrastructure.db.connection import get_session
from app.infrastructure.db.models import Base, BrowserSession, GithubAccount, GithubSigninState, User
from app.infrastructure.github_oauth import VerifiedGithubAuthorization
from app.infrastructure import github_user_credentials
from app.secrets import decrypt, encrypt
from app.modules.atomic.access.github_signin_transaction import issue_github_signin


NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)


class DeterministicRandom:
    def __init__(self) -> None:
        self.counter = 0

    def random_bytes(self, size: int) -> bytes:
        self.counter += 1
        return bytes([self.counter]) * size


def test_signin_material_is_independent_and_return_path_is_allowlisted() -> None:
    material = issue_github_signin(return_path="/setup", now=NOW, random=DeterministicRandom())
    assert len(material.state) == 43
    assert len(material.transaction_cookie) == 43
    assert material.state != material.transaction_cookie
    assert material.state not in repr(material)
    assert material.transaction_cookie not in repr(material)
    assert material.pkce_verifier not in repr(material)
    with pytest.raises(ValueError):
        issue_github_signin(return_path="//attacker.test", now=NOW, random=DeterministicRandom())


@pytest.mark.asyncio
async def test_github_signin_provisions_by_numeric_id_and_replay_fails(tmp_path, monkeypatch) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'signin.sqlite'}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def session_override():
        async with sessions() as database_session:
            yield database_session

    settings = SimpleNamespace(
        github_app_access_enabled=True,
        github_app_client_id="client-id",
        github_app_client_secret="client-secret",
        github_admin_user_ids=frozenset({4242}),
        session_secret="session-secret",
        token_encryption_key="credential-encryption-key",
        public_base_url="https://scan.example.test",
    )
    app = FastAPI()
    app.state.settings = settings
    app.include_router(github_auth.router)
    app.dependency_overrides[get_session] = session_override

    def verified(**_kwargs) -> VerifiedGithubAuthorization:
        return VerifiedGithubAuthorization(
            github_user_id=4242,
            login="octocat",
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in_seconds=28_800,
        )

    monkeypatch.setattr(github_auth, "exchange_and_verify_github_authorization", verified)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://scan.example.test") as client:
        started = await client.get("/auth/login", params={"next": "/setup"})
        assert started.status_code == 302
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(started.headers["location"]).query)
        assert query["redirect_uri"] == ["https://scan.example.test/auth/github/callback"]
        assert query["code_challenge_method"] == ["S256"]
        state = query["state"][0]

        callback = await client.get("/auth/github/callback", params={"code": "code", "state": state})
        assert callback.status_code == 302
        assert callback.headers["location"] == "/setup"
        assert client.cookies.get("as_session", domain="scan.example.test")
        replay = await client.get("/auth/github/callback", params={"code": "code", "state": state})
        assert replay.status_code == 401

    async with sessions() as database_session:
        user = (await database_session.execute(select(User))).scalar_one()
        account = (await database_session.execute(select(GithubAccount))).scalar_one()
        state_row = (await database_session.execute(select(GithubSigninState))).scalar_one()
        browser_session = (await database_session.execute(select(BrowserSession))).scalar_one()
        assert (user.email, user.github_login, user.role) == (None, "octocat", "admin")
        assert (account.github_user_id, account.user_id) == (4242, user.id)
        assert state_row.consumed_at is not None
        assert browser_session.user_id == user.id
    await engine.dispose()


@pytest.mark.asyncio
async def test_expiring_user_authorization_rotates_and_reverifies_identity(
    session, monkeypatch
) -> None:
    user = User(email=None, github_login="octocat", role="user", created_at=NOW)
    session.add(user)
    await session.flush()
    account = GithubAccount(
        user_id=user.id,
        github_user_id=4242,
        login_at_last_verify="octocat",
        encrypted_user_token=encrypt("old-access", "credential-key"),
        encrypted_refresh_token=encrypt("old-refresh", "credential-key"),
        credential_key_id="primary",
        token_expires_at=NOW + dt.timedelta(minutes=1),
        linked_at=NOW,
        verified_at=NOW,
        created_at=NOW,
    )
    session.add(account)
    await session.commit()

    monkeypatch.setattr(
        github_user_credentials,
        "refresh_and_verify_github_authorization",
        lambda **_kwargs: VerifiedGithubAuthorization(
            github_user_id=4242,
            login="octocat-renamed",
            access_token="new-access",
            refresh_token="new-refresh",
            expires_in_seconds=28_800,
        ),
    )
    settings = SimpleNamespace(
        github_app_client_id="client-id",
        github_app_client_secret="client-secret",
        token_encryption_key="credential-key",
    )

    token = await github_user_credentials.usable_github_access_token(
        session,
        user_id=user.id,
        settings=settings,
        now=NOW,
    )

    assert token == "new-access"
    await session.refresh(account)
    assert account.login_at_last_verify == "octocat-renamed"
    assert decrypt(account.encrypted_refresh_token or "", "credential-key") == "new-refresh"


@pytest.mark.asyncio
async def test_rotated_user_authorization_rejects_identity_change(session, monkeypatch) -> None:
    user = User(email=None, github_login="octocat", role="user", created_at=NOW)
    session.add(user)
    await session.flush()
    account = GithubAccount(
        user_id=user.id,
        github_user_id=4242,
        encrypted_user_token=encrypt("old-access", "credential-key"),
        encrypted_refresh_token=encrypt("old-refresh", "credential-key"),
        token_expires_at=NOW,
        created_at=NOW,
    )
    session.add(account)
    await session.commit()
    monkeypatch.setattr(
        github_user_credentials,
        "refresh_and_verify_github_authorization",
        lambda **_kwargs: VerifiedGithubAuthorization(
            github_user_id=9999,
            login="attacker",
            access_token="wrong-access",
            refresh_token="wrong-refresh",
            expires_in_seconds=28_800,
        ),
    )
    settings = SimpleNamespace(
        github_app_client_id="client-id",
        github_app_client_secret="client-secret",
        token_encryption_key="credential-key",
    )

    assert (
        await github_user_credentials.usable_github_access_token(
            session,
            user_id=user.id,
            settings=settings,
            now=NOW,
        )
        is None
    )
    await session.refresh(account)
    assert decrypt(account.encrypted_user_token or "", "credential-key") == "old-access"
