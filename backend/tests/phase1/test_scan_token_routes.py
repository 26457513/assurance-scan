"""Persistence and thin HTTP boundary tests for scan-upload tokens."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps_scan_token import require_scan_token_principal
from app.api.routes.scan_tokens import router
from app.infrastructure.db.connection import get_session
from app.infrastructure.db.models import (
    ApiToken,
    Base,
    GithubAppInstallation,
    GithubInstallationRepository,
    Project,
    ProjectMembership,
    User,
)
from app.infrastructure.db.repositories.api_tokens import (
    SecureScanTokenRandom,
    SqlAlchemyScanTokenRepository,
    SystemScanTokenClock,
)
from app.modules.atomic.access.browser_auth import mint_session
from app.modules.atomic.access.scan_token import (
    CreateScanTokenCommand,
    ScanTokenActiveLimitError,
    ScanTokenPrincipal,
    create_scan_token,
)


PUBLIC_ORIGIN = "https://scan.example.test"
SESSION_SECRET = "test-session-secret-at-least-32-bytes"


@dataclass
class RouteHarness:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    settings: SimpleNamespace

    def sign_in(self, email: str) -> None:
        self.client.cookies.set(
            "as_session",
            mint_session(email, SESSION_SECRET),
            domain="scan.example.test",
            path="/",
        )

    async def csrf(self) -> str:
        response = await self.client.get("/api/users/me/scan-tokens")
        assert response.status_code == 200, response.text
        return str(response.json()["csrf_token"])

    async def issue(self, label: str = "Laptop", days: int = 90):
        csrf = await self.csrf()
        return await self.client.post(
            "/api/users/me/scan-tokens",
            json={"label": label, "expires_in_days": days},
            headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
        )


@pytest_asyncio.fixture
async def harness(tmp_path) -> RouteHarness:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tokens.sqlite'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        alice = User(email="alice@example.test", role="user")
        bob = User(email="bob@example.test", role="user")
        disabled = User(
            email="disabled@example.test",
            role="user",
            disabled_at=datetime.now(timezone.utc),
        )
        project = Project(
            tag="eligible",
            github_repo="example/eligible",
            github_repo_key="example/eligible",
            github_repository_id=424242,
        )
        session.add_all((alice, bob, disabled, project))
        await session.flush()
        now = datetime.now(timezone.utc)
        session.add_all(
            (
                GithubAppInstallation(
                    github_installation_id=9001,
                    github_owner_id=26457513,
                    owner_login_at_last_verify="example",
                    account_type="organization",
                    repository_selection="selected",
                    created_at=now,
                    updated_at=now,
                ),
                GithubInstallationRepository(
                    github_installation_id=9001,
                    github_repository_id=424242,
                    project_id=project.id,
                    repository_full_name="example/eligible",
                    github_owner_id=26457513,
                    default_branch="main",
                    visibility="private",
                    archived=False,
                    disabled=False,
                    repository_verified_at=now,
                    enabled_at=now,
                    updated_at=now,
                ),
                ProjectMembership(
                    user_id=alice.id,
                    project_id=project.id,
                    permission="upload",
                    source="github_app",
                    verified_at=now,
                    expires_at=now + timedelta(minutes=5),
                ),
            )
        )
        await session.commit()

    async def session_override():
        async with sessions() as session:
            yield session

    settings = SimpleNamespace(
        google_client_id="google-client",
        google_client_secret="google-secret",
        session_secret=SESSION_SECRET,
        public_base_url=PUBLIC_ORIGIN,
        scan_token_creation_enabled=True,
        scan_token_creation_user_allowlist=frozenset(),
    )
    app = FastAPI()
    app.state.settings = settings
    app.include_router(router, prefix="/api")

    @app.get("/api/test/bearer")
    async def bearer_probe(
        principal: ScanTokenPrincipal = Depends(require_scan_token_principal),
    ) -> dict[str, object]:
        return {"user_id": principal.user_id, "token_id": principal.token_id}

    app.dependency_overrides[get_session] = session_override
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=PUBLIC_ORIGIN,
    ) as client:
        yield RouteHarness(client=client, sessions=sessions, settings=settings)
    await engine.dispose()


async def test_get_mints_bound_http_only_strict_csrf_cookie(harness: RouteHarness) -> None:
    harness.sign_in("alice@example.test")
    response = await harness.client.get("/api/users/me/scan-tokens")
    assert response.status_code == 200
    assert response.json()["tokens"] == []
    assert response.json()["creation_enabled"] is True
    csrf = response.json()["csrf_token"]
    cookie = response.headers["set-cookie"]
    assert f"as_csrf={csrf}" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Secure" in cookie
    assert response.headers["cache-control"] == "no-store"


async def test_creation_flag_fails_closed_but_list_and_revoke_remain_available(
    harness: RouteHarness,
) -> None:
    harness.sign_in("alice@example.test")
    issued = await harness.issue("Before rollout closes")
    assert issued.status_code == 201
    token_id = issued.json()["audit"]["id"]
    harness.settings.scan_token_creation_enabled = False

    blocked = await harness.issue("Blocked")
    assert blocked.status_code == 503
    assert blocked.json() == {"detail": "Scan-token creation is disabled."}
    assert blocked.headers["cache-control"] == "no-store"

    listed = await harness.client.get("/api/users/me/scan-tokens")
    assert listed.status_code == 200
    assert listed.json()["creation_enabled"] is False
    assert [token["id"] for token in listed.json()["tokens"]] == [token_id]
    csrf = listed.json()["csrf_token"]
    revoked = await harness.client.delete(
        f"/api/users/me/scan-tokens/{token_id}",
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    assert revoked.status_code == 200


async def test_creation_user_canary_denies_without_echoing_account_or_allowlist(
    harness: RouteHarness,
) -> None:
    harness.sign_in("alice@example.test")
    harness.settings.scan_token_creation_user_allowlist = frozenset(
        {"admin@example.test"}
    )
    response = await harness.issue("Blocked canary")
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Scan-token creation is not enabled for this account."
    }
    assert "alice@example.test" not in response.text
    assert "admin@example.test" not in response.text
    assert response.headers["cache-control"] == "no-store"

    listed = await harness.client.get("/api/users/me/scan-tokens")
    assert listed.json()["creation_enabled"] is False

    harness.settings.scan_token_creation_user_allowlist = frozenset(
        {"alice@example.test"}
    )
    listed = await harness.client.get("/api/users/me/scan-tokens")
    assert listed.json()["creation_enabled"] is True
    assert (await harness.issue("Allowed canary")).status_code == 201


async def test_creation_requires_current_github_app_upload_entitlement_without_admin_bypass(
    harness: RouteHarness,
) -> None:
    harness.sign_in("bob@example.test")
    listed = await harness.client.get("/api/users/me/scan-tokens")
    assert listed.status_code == 200
    assert listed.json()["creation_enabled"] is False
    denied = await harness.issue("No entitlement")
    assert denied.status_code == 403
    assert denied.json() == {
        "detail": "Current GitHub write access to an enabled repository is required."
    }

    async with harness.sessions() as session:
        alice = (
            await session.execute(select(User).where(User.email == "alice@example.test"))
        ).scalar_one()
        alice.role = "admin"
        membership = (
            await session.execute(
                select(ProjectMembership).where(ProjectMembership.user_id == alice.id)
            )
        ).scalar_one()
        membership.source = "manual"
        membership.permission = "manage"
        membership.expires_at = None
        await session.commit()

    harness.sign_in("alice@example.test")
    listed = await harness.client.get("/api/users/me/scan-tokens")
    assert listed.json()["creation_enabled"] is False
    assert (await harness.issue("Admin cannot bypass")).status_code == 403


async def test_access_loss_blocks_creation_but_preserves_owned_list_and_revoke(
    harness: RouteHarness,
) -> None:
    harness.sign_in("alice@example.test")
    issued = await harness.issue("Existing laptop")
    assert issued.status_code == 201
    token_id = issued.json()["audit"]["id"]

    async with harness.sessions() as session:
        membership = (await session.execute(select(ProjectMembership))).scalar_one()
        membership.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    listed = await harness.client.get("/api/users/me/scan-tokens")
    assert listed.status_code == 200
    assert listed.json()["creation_enabled"] is False
    assert [row["id"] for row in listed.json()["tokens"]] == [token_id]
    blocked = await harness.issue("Replacement blocked")
    assert blocked.status_code == 403

    csrf = await harness.csrf()
    revoked = await harness.client.delete(
        f"/api/users/me/scan-tokens/{token_id}",
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    assert revoked.status_code == 200
    assert revoked.json() == {"status": "revoked"}


async def test_creation_requires_active_project_repository_and_installation(
    harness: RouteHarness,
) -> None:
    harness.sign_in("alice@example.test")
    assert (await harness.client.get("/api/users/me/scan-tokens")).json()[
        "creation_enabled"
    ] is True

    async with harness.sessions() as session:
        repository = (await session.execute(select(GithubInstallationRepository))).scalar_one()
        repository.disabled = True
        await session.commit()
    assert (await harness.client.get("/api/users/me/scan-tokens")).json()[
        "creation_enabled"
    ] is False

    async with harness.sessions() as session:
        repository = (await session.execute(select(GithubInstallationRepository))).scalar_one()
        repository.disabled = False
        project = (await session.execute(select(Project))).scalar_one()
        project.hidden = True
        await session.commit()
    assert (await harness.client.get("/api/users/me/scan-tokens")).json()[
        "creation_enabled"
    ] is False

    async with harness.sessions() as session:
        project = (await session.execute(select(Project))).scalar_one()
        project.hidden = False
        installation = (await session.execute(select(GithubAppInstallation))).scalar_one()
        installation.suspended_at = datetime.now(timezone.utc)
        await session.commit()
    assert (await harness.client.get("/api/users/me/scan-tokens")).json()[
        "creation_enabled"
    ] is False


async def test_issue_returns_plaintext_once_and_persists_only_digest(
    harness: RouteHarness,
) -> None:
    harness.sign_in("alice@example.test")
    response = await harness.issue()
    assert response.status_code == 201, response.text
    plaintext = response.json()["token"]
    assert plaintext.startswith("asu_v1_")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"

    async with harness.sessions() as session:
        row = (await session.execute(select(ApiToken))).scalar_one()
        assert isinstance(row.secret_digest, bytes)
        assert len(row.secret_digest) == 32
        assert plaintext not in repr(row.__dict__)
        assert row.label == "Laptop"
        assert row.label_key == "laptop"

    listed = await harness.client.get("/api/users/me/scan-tokens")
    assert listed.status_code == 200
    assert listed.json()["tokens"][0]["label"] == "Laptop"
    assert "token" not in listed.json()["tokens"][0]


async def test_issue_requires_signed_double_submit_and_exact_origin(
    harness: RouteHarness,
) -> None:
    harness.sign_in("alice@example.test")
    csrf = await harness.csrf()
    body = {"label": "Laptop", "expires_in_days": 90}
    missing = await harness.client.post(
        "/api/users/me/scan-tokens",
        json=body,
        headers={"Origin": PUBLIC_ORIGIN},
    )
    wrong_origin = await harness.client.post(
        "/api/users/me/scan-tokens",
        json=body,
        headers={"Origin": "https://attacker.example", "X-CSRF-Token": csrf},
    )
    wrong_header = await harness.client.post(
        "/api/users/me/scan-tokens",
        json=body,
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": "wrong"},
    )
    assert {missing.status_code, wrong_origin.status_code, wrong_header.status_code} == {403}

    accepted = await harness.client.post(
        "/api/users/me/scan-tokens",
        json=body,
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    assert accepted.status_code == 201


async def test_issue_accepts_only_locked_ui_expiry_choices(harness: RouteHarness) -> None:
    harness.sign_in("alice@example.test")
    csrf = await harness.csrf()
    response = await harness.client.post(
        "/api/users/me/scan-tokens",
        json={"label": "Laptop", "expires_in_days": 365},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 422


async def test_label_conflict_and_active_limit_are_enforced(harness: RouteHarness) -> None:
    harness.sign_in("alice@example.test")
    assert (await harness.issue("Ｌａｐｔｏｐ")).status_code == 201
    assert (await harness.issue("laptop")).status_code == 409
    for label in ("Workstation", "CI box", "Travel", "Backup"):
        assert (await harness.issue(label)).status_code == 201
    limited = await harness.issue("Sixth")
    assert limited.status_code == 409
    assert "limit" in limited.json()["detail"]


async def test_token_creation_rate_limit_counts_recently_revoked_tokens(
    harness: RouteHarness,
) -> None:
    harness.sign_in("alice@example.test")
    for index in range(5):
        issued = await harness.issue(f"device-{index}")
        assert issued.status_code == 201
        csrf = await harness.csrf()
        revoked = await harness.client.delete(
            f"/api/users/me/scan-tokens/{issued.json()['audit']['id']}",
            headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
        )
        assert revoked.status_code == 200

    limited = await harness.issue("device-six")
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "3600"


async def test_invalid_bearer_attempts_are_rate_limited(harness: RouteHarness) -> None:
    for _attempt in range(10):
        response = await harness.client.get(
            "/api/test/bearer",
            headers={"Authorization": "Bearer malformed"},
        )
        assert response.status_code == 401

    limited = await harness.client.get(
        "/api/test/bearer",
        headers={"Authorization": "Bearer malformed"},
    )
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["retry-after"]) <= 600


async def test_revoke_is_owned_and_idempotent(harness: RouteHarness) -> None:
    harness.sign_in("alice@example.test")
    issued = await harness.issue()
    token_id = issued.json()["audit"]["id"]

    harness.sign_in("bob@example.test")
    bob_csrf = await harness.csrf()
    other_user = await harness.client.delete(
        f"/api/users/me/scan-tokens/{token_id}",
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": bob_csrf},
    )
    assert other_user.status_code == 200
    assert other_user.json() == {"status": "revoked"}
    async with harness.sessions() as session:
        assert (await session.get(ApiToken, token_id)).revoked_at is None

    harness.sign_in("alice@example.test")
    alice_csrf = await harness.csrf()
    first = await harness.client.delete(
        f"/api/users/me/scan-tokens/{token_id}",
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": alice_csrf},
    )
    second = await harness.client.delete(
        f"/api/users/me/scan-tokens/{token_id}",
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": alice_csrf},
    )
    missing = await harness.client.delete(
        "/api/users/me/scan-tokens/00000000-0000-4000-8000-000000000000",
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": alice_csrf},
    )
    assert (first.status_code, second.status_code, missing.status_code) == (200, 200, 200)


async def test_routes_reject_missing_disabled_auth_off_and_basic_only_users(
    harness: RouteHarness,
) -> None:
    harness.sign_in("missing@example.test")
    assert (await harness.client.get("/api/users/me/scan-tokens")).status_code == 401

    harness.sign_in("disabled@example.test")
    assert (await harness.client.get("/api/users/me/scan-tokens")).status_code == 403

    harness.sign_in("alice@example.test")
    harness.settings.google_client_id = ""
    auth_off = await harness.client.get("/api/users/me/scan-tokens")
    assert auth_off.status_code == 401
    harness.client.cookies.clear()
    basic_only = await harness.client.get(
        "/api/users/me/scan-tokens",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert basic_only.status_code == 401


async def test_bearer_dependency_uniformly_maps_invalid_token_states(
    harness: RouteHarness,
) -> None:
    harness.sign_in("alice@example.test")
    issued = await harness.issue()
    plaintext = issued.json()["token"]
    token_id = issued.json()["audit"]["id"]

    valid = await harness.client.get("/api/test/bearer", headers={"Authorization": f"Bearer {plaintext}"})
    assert valid.status_code == 200
    wrong = await harness.client.get("/api/test/bearer", headers={"Authorization": "Bearer malformed"})
    assert wrong.status_code == 401
    assert wrong.headers["www-authenticate"] == "Bearer"

    async with harness.sessions() as session:
        row = await session.get(ApiToken, token_id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()
    expired = await harness.client.get("/api/test/bearer", headers={"Authorization": f"Bearer {plaintext}"})
    assert expired.status_code == 401

    async with harness.sessions() as session:
        row = await session.get(ApiToken, token_id)
        row.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        row.revoked_at = datetime.now(timezone.utc)
        await session.commit()
    revoked = await harness.client.get("/api/test/bearer", headers={"Authorization": f"Bearer {plaintext}"})
    assert revoked.status_code == 401

    async with harness.sessions() as session:
        row = await session.get(ApiToken, token_id)
        row.revoked_at = None
        user = await session.get(User, row.user_id)
        user.disabled_at = datetime.now(timezone.utc)
        await session.commit()
    disabled = await harness.client.get("/api/test/bearer", headers={"Authorization": f"Bearer {plaintext}"})
    assert disabled.status_code == 401


async def test_repository_serializes_concurrent_active_limit(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.sqlite'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        user = User(email="parallel@example.test", role="user")
        session.add(user)
        await session.commit()
        user_id = user.id

    async def issue(index: int):
        async with sessions() as session:
            return await create_scan_token(
                CreateScanTokenCommand(user_id=user_id, label=f"device-{index}"),
                repository=SqlAlchemyScanTokenRepository(session),
                clock=SystemScanTokenClock(),
                random=SecureScanTokenRandom(),
            )

    results = await asyncio.gather(*(issue(index) for index in range(6)), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 5
    assert sum(isinstance(result, ScanTokenActiveLimitError) for result in results) == 1
    async with sessions() as session:
        count = (await session.execute(select(func.count()).select_from(ApiToken))).scalar_one()
    assert count == 5
    await engine.dispose()
