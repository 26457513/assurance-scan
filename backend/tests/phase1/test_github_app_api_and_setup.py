"""Fixed GitHub App API and feature-gated setup-return integration tests."""

from __future__ import annotations

import base64
import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import github_app_setup as setup_routes
from app.infrastructure.db.connection import get_session
from app.infrastructure.db.models import Base, GithubAccount, Project, User
from app.infrastructure.github_app_api import (
    GITHUB_API_ROOT,
    GithubApiResponse,
    GithubAppApiError,
    GithubAppInstallationState,
    GithubAppUserEntitlementClient,
    GithubRateLimitError,
    UrllibGithubHttp,
    create_github_app_jwt,
    fetch_authoritative_installation,
    fetch_authoritative_installation_for_user,
    fetch_github_app_installation_states,
    load_github_app_private_key,
)
from app.modules.atomic.access.browser_auth import mint_session
from app.modules.atomic.access.github_membership_projection import GithubProjectPermission
from app.modules.atomic.access.github_repository_reconciliation import (
    GithubAccountType,
    GithubInstallationSnapshot,
    GithubRepositorySnapshot,
    GithubRepositoryVisibility,
    GithubSelection,
)
from app.secrets import encrypt


NOW = dt.datetime(2026, 9, 2, 20, 0, tzinfo=dt.timezone.utc)


class FakeGithubHttp:
    def __init__(self, *, user_has_access: bool = True) -> None:
        self.user_has_access = user_has_access
        self.requests: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> GithubApiResponse:
        self.requests.append((method, url, headers, body))
        if url.startswith(f"{GITHUB_API_ROOT}/user/installations?"):
            installations = [{"id": 9001}] if self.user_has_access else []
            return GithubApiResponse({"installations": installations}, {})
        if url.startswith(f"{GITHUB_API_ROOT}/user/installations/9001/repositories?"):
            return GithubApiResponse(
                {
                    "repositories": [
                        {"id": 424242, "permissions": {"pull": True}},
                        {"id": 424243, "permissions": {"push": True}},
                        {"id": 424244, "permissions": {"admin": True}},
                    ]
                },
                {},
            )
        if url.startswith(f"{GITHUB_API_ROOT}/app/installations?"):
            return GithubApiResponse(
                [
                    {"id": 9001, "suspended_at": None},
                    {"id": 9002, "suspended_at": "2026-09-02T19:00:00Z"},
                ],
                {},
            )
        if url == f"{GITHUB_API_ROOT}/app/installations/9001":
            return GithubApiResponse(
                {
                    "id": 9001,
                    "account": {"id": 26457513, "login": "example-org", "type": "Organization"},
                    "repository_selection": "selected",
                    "suspended_at": None,
                },
                {},
            )
        if url == f"{GITHUB_API_ROOT}/app/installations/9001/access_tokens":
            return GithubApiResponse({"token": "installation-token"}, {})
        if url.startswith(f"{GITHUB_API_ROOT}/installation/repositories?"):
            return GithubApiResponse(
                {
                    "repositories": [
                        {
                            "id": 424242,
                            "full_name": "example-org/example-repo",
                            "owner": {"id": 26457513},
                            "default_branch": "main",
                            "visibility": "private",
                            "archived": False,
                            "disabled": False,
                        }
                    ]
                },
                {"etag": '"repositories-v1"'},
            )
        raise AssertionError(f"unexpected request: {method} {url}")


def _private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _private_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_app_jwt_is_short_lived_rs256_and_cryptographically_valid() -> None:
    key = _private_key()

    token = create_github_app_jwt(github_app_id="12345", private_key_pem=_private_pem(key), now=NOW)

    header_part, claims_part, signature_part = token.split(".")
    header = json.loads(_decode(header_part))
    claims = json.loads(_decode(claims_part))
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert claims == {
        "exp": int(NOW.timestamp()) + 540,
        "iat": int(NOW.timestamp()) - 60,
        "iss": "12345",
    }
    key.public_key().verify(
        _decode(signature_part),
        f"{header_part}.{claims_part}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_user_proof_precedes_app_token_and_complete_scope_fetch() -> None:
    http = FakeGithubHttp()

    snapshot = fetch_authoritative_installation_for_user(
        user_token="user-token",
        github_app_id="12345",
        private_key_pem=_private_pem(_private_key()),
        github_installation_id=9001,
        now=NOW,
        http=http,
    )

    assert snapshot.github_installation_id == 9001
    assert snapshot.github_owner_id == 26457513
    assert snapshot.repositories_etag == '"repositories-v1"'
    assert [item.github_repository_id for item in snapshot.repositories] == [424242]
    assert http.requests[0][1].startswith(f"{GITHUB_API_ROOT}/user/installations?")
    assert http.requests[0][2]["Authorization"] == "Bearer user-token"
    assert http.requests[-1][2]["Authorization"] == "Bearer installation-token"
    assert all(request[1].startswith(f"{GITHUB_API_ROOT}/") for request in http.requests)


def test_user_entitlements_are_installation_scoped_and_permission_mapped() -> None:
    entitlements = GithubAppUserEntitlementClient(FakeGithubHttp()).fetch("user-token")

    assert [item.github_repository_id for item in entitlements] == [424242, 424243, 424244]
    assert [item.github_installation_id for item in entitlements] == [9001, 9001, 9001]
    assert [item.permission for item in entitlements] == [
        GithubProjectPermission.VIEW,
        GithubProjectPermission.UPLOAD,
        GithubProjectPermission.MANAGE,
    ]


def test_worker_fetch_uses_app_credentials_without_a_user_token() -> None:
    http = FakeGithubHttp()

    snapshot = fetch_authoritative_installation(
        github_app_id="12345",
        private_key_pem=_private_pem(_private_key()),
        github_installation_id=9001,
        now=NOW,
        http=http,
    )

    assert snapshot.github_installation_id == 9001
    assert http.requests[0][1] == f"{GITHUB_API_ROOT}/app/installations/9001"
    assert all("/user/installations" not in request[1] for request in http.requests)


def test_complete_app_installation_listing_carries_only_authoritative_state() -> None:
    states = fetch_github_app_installation_states(
        github_app_id="12345",
        private_key_pem=_private_pem(_private_key()),
        now=NOW,
        http=FakeGithubHttp(),
    )

    assert states == (
        GithubAppInstallationState(github_installation_id=9001, suspended_at=None),
        GithubAppInstallationState(
            github_installation_id=9002,
            suspended_at=dt.datetime(2026, 9, 2, 19, 0, tzinfo=dt.timezone.utc),
        ),
    )


def test_inaccessible_installation_fails_before_app_credentials_are_used() -> None:
    http = FakeGithubHttp(user_has_access=False)

    with pytest.raises(GithubAppApiError, match="cannot access"):
        fetch_authoritative_installation_for_user(
            user_token="user-token",
            github_app_id="12345",
            private_key_pem=_private_pem(_private_key()),
            github_installation_id=9001,
            now=NOW,
            http=http,
        )

    assert len(http.requests) == 1


def test_private_key_loader_rejects_symlinks(tmp_path) -> None:
    key_file = tmp_path / "app.pem"
    key_file.write_bytes(_private_pem(_private_key()))
    linked = tmp_path / "linked.pem"
    linked.symlink_to(key_file)

    assert load_github_app_private_key(str(key_file)).startswith(b"-----BEGIN PRIVATE KEY-----")
    with pytest.raises(GithubAppApiError, match="invalid"):
        load_github_app_private_key(str(linked))


def test_http_adapter_classifies_and_bounds_explicit_rate_limit(monkeypatch) -> None:
    headers = Message()
    headers["Retry-After"] = "120"
    error = urllib.error.HTTPError(
        f"{GITHUB_API_ROOT}/user/installations",
        429,
        "rate limited",
        headers,
        None,
    )

    class FailingOpener:
        def open(self, _request, timeout):
            assert timeout == 15
            raise error

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: FailingOpener())
    before = dt.datetime.now(dt.timezone.utc)
    with pytest.raises(GithubRateLimitError) as raised:
        UrllibGithubHttp().request(
            "GET",
            f"{GITHUB_API_ROOT}/user/installations",
            headers={},
        )
    assert before + dt.timedelta(seconds=119) <= raised.value.retry_at
    assert raised.value.retry_at <= before + dt.timedelta(seconds=121)


@pytest.mark.asyncio
async def test_setup_return_is_state_bound_user_proven_and_reconciled(tmp_path, monkeypatch) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'setup.sqlite'}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def session_override():
        async with sessions() as database_session:
            yield database_session

    key_file = tmp_path / "github-app.pem"
    key_file.write_bytes(_private_pem(_private_key()))
    settings = SimpleNamespace(
        github_app_access_enabled=True,
        github_app_id="12345",
        github_app_slug="assurance-scan",
        github_app_private_key_path=str(key_file),
        token_encryption_key="credential-key",
        public_base_url="https://scan.example.test",
        session_secret="session-secret-at-least-thirty-two-bytes",
    )
    app = FastAPI()
    app.state.settings = settings
    app.include_router(setup_routes.router, prefix="/api")
    app.dependency_overrides[get_session] = session_override
    async with sessions() as database_session:
        user = User(email="owner@example.test", role="user", created_at=NOW)
        database_session.add(user)
        await database_session.flush()
        database_session.add(
            GithubAccount(
                user_id=user.id,
                github_user_id=583231,
                login_at_last_verify="octocat",
                encrypted_user_token=encrypt("user-token", settings.token_encryption_key),
                credential_key_id="primary",
                token_expires_at=NOW + dt.timedelta(hours=1),
                linked_at=NOW,
                verified_at=NOW,
                created_at=NOW,
            )
        )
        await database_session.commit()

    expected = GithubInstallationSnapshot(
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
    monkeypatch.setattr(
        setup_routes,
        "fetch_authoritative_installation_for_user",
        lambda **_kwargs: expected,
    )
    refresh = AsyncMock(return_value=True)
    monkeypatch.setattr(setup_routes, "sync_github_app_memberships", refresh)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://scan.example.test") as client:
        client.cookies.set(
            "as_session",
            mint_session("owner@example.test", settings.session_secret),
            domain="scan.example.test",
            path="/",
        )
        started = await client.get("/api/v2/github/install/start")
        assert started.status_code == 302
        parsed = urllib.parse.urlsplit(started.headers["location"])
        assert parsed.netloc == "github.com"
        assert parsed.path == "/apps/assurance-scan/installations/new"
        state = urllib.parse.parse_qs(parsed.query)["state"][0]
        finished = await client.get(
            "/api/v2/github/setup-return",
            params={"state": state, "setup_action": "install", "installation_id": 9001},
        )
        assert finished.status_code == 302
        assert finished.headers["location"] == "/setup?github_install=ready"
        refresh.assert_awaited_once()

    async with sessions() as database_session:
        project = (await database_session.execute(select(Project))).scalar_one()
        assert project.github_repository_id == 424242
        assert project.github_repo == "example-org/example-repo"
    await engine.dispose()


@pytest.mark.asyncio
async def test_setup_routes_are_invisible_when_feature_is_disabled() -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        github_app_access_enabled=False,
        session_secret="",
    )
    app.include_router(setup_routes.router, prefix="/api")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://scan.example.test") as client:
        response = await client.get("/api/v2/github/install/start")
    assert response.status_code == 404
