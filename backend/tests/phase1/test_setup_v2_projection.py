"""Version-two Setup state, entitlement and privacy boundary tests."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps_roles import get_current_user
from app.api.routes import setup as setup_routes
from app.infrastructure.db.connection import get_session
from app.infrastructure.db.models import (
    ApiToken,
    Base,
    GithubAccount,
    GithubAppInstallation,
    GithubInstallationRepository,
    IngestAttempt,
    Project,
    ProjectMembership,
    Run,
    User,
)
from app.infrastructure.db.repositories.setup_projection import (
    SetupCursorError,
    SqlAlchemySetupProjectionRepository,
)
from app.modules.atomic.access.setup_state import setup_payload
from app.modules.atomic.access.setup_state.models import (
    SetupRepositoryPermission,
    SetupSelectionStatus,
)
from app.modules.workflows.setup_bootstrap import SetupLinks, setup_bootstrap


NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)
SHA = "a" * 40
HASH = "b" * 64


class NeverCalledRepository:
    async def load_bootstrap(self, **_kwargs):
        raise AssertionError("signed-out Setup must not access account data")


@pytest.mark.asyncio
async def test_signed_out_payload_contains_no_account_data_and_stringifies_no_selection() -> None:
    result = await setup_bootstrap(
        user_id=None,
        selected_repository_id=None,
        installations_cursor=None,
        now=NOW,
        repository=NeverCalledRepository(),  # type: ignore[arg-type]
        links=SetupLinks(sign_in_url="/auth/login?next=/setup", install_url="/install"),
    )

    assert setup_payload(result) == {
        "version": 2,
        "selection": {"status": "none", "requested_repository_id": None},
        "state": {"sign_in_url": "/auth/login?next=/setup", "kind": "signed_out"},
        "installations": [],
        "installations_next_cursor": None,
        "machine_tokens": [],
        "latest_local_run": None,
    }


@pytest.mark.asyncio
async def test_projection_is_entitlement_first_and_local_evidence_is_owner_scoped(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'setup.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        owner = User(email="owner@example.com", role="user")
        other = User(email="other@example.com", role="user")
        session.add_all((owner, other))
        await session.flush()
        assert owner.id is not None and other.id is not None
        project = Project(
            tag="service",
            github_repo="acme/service",
            github_repo_key="acme/service",
            github_repository_id=60_000_000_000_000_001,
        )
        hidden_project = Project(
            tag="secret",
            github_repo="acme/secret",
            github_repo_key="acme/secret",
            github_repository_id=60_000_000_000_000_002,
        )
        session.add_all((project, hidden_project))
        await session.flush()
        installation = GithubAppInstallation(
            github_installation_id=80_000_000_000_000_001,
            github_owner_id=70_000_000_000_000_001,
            owner_login_at_last_verify="acme",
            account_type="organization",
            repository_selection="selected",
            created_at=NOW,
            updated_at=NOW,
            last_reconciled_at=NOW,
        )
        session.add(installation)
        session.add_all(
            (
                GithubInstallationRepository(
                    github_installation_id=installation.github_installation_id,
                    github_repository_id=project.github_repository_id,
                    project_id=project.id,
                    repository_full_name="acme/service",
                    github_owner_id=installation.github_owner_id,
                    default_branch="main",
                    visibility="private",
                    repository_verified_at=NOW,
                    enabled_at=NOW,
                    updated_at=NOW,
                ),
                GithubInstallationRepository(
                    github_installation_id=installation.github_installation_id,
                    github_repository_id=hidden_project.github_repository_id,
                    project_id=hidden_project.id,
                    repository_full_name="acme/secret",
                    github_owner_id=installation.github_owner_id,
                    default_branch="main",
                    visibility="private",
                    repository_verified_at=NOW,
                    enabled_at=NOW,
                    updated_at=NOW,
                ),
            )
        )
        session.add(
            ProjectMembership(
                user_id=owner.id,
                project_id=project.id,
                permission="upload",
                source="github_app",
                verified_at=NOW,
                expires_at=NOW + dt.timedelta(minutes=5),
            )
        )
        session.add_all(
            (
                GithubAccount(
                    user_id=owner.id,
                    github_user_id=90_071_992_547_409_930,
                    login_at_last_verify="octocat",
                    encrypted_user_token="opaque",
                    linked_at=NOW,
                    verified_at=NOW,
                ),
                GithubAccount(
                    user_id=other.id,
                    github_user_id=90_071_992_547_409_931,
                    login_at_last_verify="other",
                    encrypted_user_token="opaque",
                    linked_at=NOW,
                    verified_at=NOW,
                ),
            )
        )
        owner_token = _token("00000000-0000-0000-0000-000000000001", owner.id, "owner-laptop")
        other_token = _token("00000000-0000-0000-0000-000000000002", other.id, "other-laptop")
        session.add_all((owner_token, other_token))
        session.add_all(
            (
                _local_run(
                    "local-owner",
                    project.id,
                    owner.id,
                    owner_token.id,
                    1,
                    NOW - dt.timedelta(minutes=2),
                    "owner-laptop",
                ),
                _local_run(
                    "local-other",
                    project.id,
                    other.id,
                    other_token.id,
                    2,
                    NOW - dt.timedelta(minutes=1),
                    "other-laptop",
                ),
            )
        )
        session.add(
            IngestAttempt(
                id="00000000-0000-0000-0000-000000000003",
                correlation_id="00000000-0000-0000-0000-000000000004",
                origin="github",
                project_id=project.id,
                principal_kind="github_oidc",
                principal_reference_hash=HASH,
                canonical_request_key_hash=HASH,
                outcome="rejected",
                reason_code="invalid_bundle",
                retryable=False,
                wire_bytes=100,
                received_at=NOW - dt.timedelta(minutes=3),
                completed_at=NOW - dt.timedelta(minutes=3),
                expires_at=NOW + dt.timedelta(days=30),
            )
        )
        await session.commit()

        repository = SqlAlchemySetupProjectionRepository(session)
        page = await repository.search_repositories(
            user_id=owner.id,
            github_installation_id=installation.github_installation_id,
            query="",
            cursor=None,
            limit=25,
            now=NOW,
        )
        assert [item.full_name for item in page.repositories] == ["acme/service"]
        assert page.repositories[0].permission is SetupRepositoryPermission.WRITE

        other_page = await repository.search_repositories(
            user_id=other.id,
            github_installation_id=installation.github_installation_id,
            query="",
            cursor=None,
            limit=25,
            now=NOW,
        )
        assert other_page.repositories == ()

        result = await setup_bootstrap(
            user_id=owner.id,
            selected_repository_id=project.github_repository_id,
            installations_cursor=None,
            now=NOW,
            repository=repository,
            links=SetupLinks(sign_in_url="/link", install_url="/install"),
        )
        payload = setup_payload(result)
        assert result.selection.status is SetupSelectionStatus.SELECTED
        assert payload["selection"] == {
            "status": "selected",
            "requested_repository_id": "60000000000000001",
        }
        assert payload["state"] == {
            "identity": {
                "github_user_id": "90071992547409930",
                "login": "octocat",
                "avatar_url": None,
            },
            "installation": {
                "github_installation_id": "80000000000000001",
                "github_owner_id": "70000000000000001",
                "owner_login": "acme",
                "account_type": "Organization",
                "repository_selection": "selected",
                "enabled_repository_count": 1,
                "manage_url": "https://github.com/settings/installations/80000000000000001",
            },
            "repository": {
                "github_repository_id": "60000000000000001",
                "github_installation_id": "80000000000000001",
                "project_id": project.id,
                "full_name": "acme/service",
                "default_branch": "main",
                "permission": "write",
                "archived": False,
            },
            "capabilities": {"can_local_scan": True, "can_manage": False},
            "actions_readiness": {
                "attempt_id": "00000000-0000-0000-0000-000000000003",
                "attempted_at": "2026-09-02T11:57:00Z",
                "safe_code": "invalid_bundle",
                "correlation_id": "00000000-0000-0000-0000-000000000004",
                "troubleshooting_url": "/help/uploads#invalid_bundle",
                "actions_url": None,
                "kind": "rejected",
            },
            "kind": "repository_ready_write",
        }
        assert payload["latest_local_run"] == {
            "run_id": "local-owner",
            "display_title": "owner-laptop",
            "branch": "feature/owner",
            "commit_sha": SHA,
            "dirty": True,
            "status": "completed",
            "started_at": "2026-09-02T11:58:00Z",
        }
        assert [token["label"] for token in payload["machine_tokens"]] == ["owner-laptop"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_cursor_is_listing_specific_and_malformed_values_fail(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cursor.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repository = SqlAlchemySetupProjectionRepository(session)
        with pytest.raises(SetupCursorError, match="invalid"):
            await repository.search_repositories(
                user_id=1,
                github_installation_id=1,
                query="",
                cursor="not-a-valid-cursor",
                limit=25,
                now=NOW,
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_setup_http_boundary_is_feature_gated_and_caps_repository_pages(tmp_path, monkeypatch) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'route.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.state.settings = SimpleNamespace(github_app_access_enabled=False)
    app.include_router(setup_routes.router, prefix="/api")

    async def session_override():
        async with factory() as session:
            yield session

    async def anonymous_override():
        return None

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = anonymous_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        disabled = await client.get("/api/v2/setup")
        assert disabled.status_code == 404

        app.state.settings.github_app_access_enabled = True
        signed_out = await client.get("/api/v2/setup")
        assert signed_out.status_code == 200
        assert signed_out.json()["state"] == {
            "sign_in_url": "/auth/login?next=/setup",
            "kind": "signed_out",
        }
        assert signed_out.headers["cache-control"] == "no-store"

        invalid = await client.get("/api/v2/setup?github_repository_id=01")
        assert invalid.status_code == 422

        async def user_override():
            return User(id=1, email="route@example.com", role="user")

        app.dependency_overrides[get_current_user] = user_override
        monkeypatch.setattr(setup_routes, "sync_github_app_memberships", AsyncMock(return_value=True))
        capped = await client.get(
            "/api/v2/setup/repositories",
            params={"github_installation_id": "1", "limit": "999"},
        )
        assert capped.status_code == 200
        assert capped.json() == {"repositories": [], "next_cursor": None}
    await engine.dispose()


def _token(token_id: str, user_id: int, label: str) -> ApiToken:
    return ApiToken(
        id=token_id,
        user_id=user_id,
        label=label,
        label_key=label,
        selector=token_id[-16:],
        secret_digest=b"x" * 32,
        scope="scans:upload",
        token_version=1,
        expires_at=NOW + dt.timedelta(days=30),
        created_at=NOW,
    )


def _local_run(
    run_id: str,
    project_id: int,
    user_id: int,
    token_id: str,
    number: int,
    started_at: dt.datetime,
    machine: str,
) -> Run:
    return Run(
        run_id=run_id,
        project_id=project_id,
        options_json="{}",
        status="completed",
        started_at=started_at,
        completed_at=started_at + dt.timedelta(seconds=1),
        commit_sha=SHA,
        git_branch="feature/owner",
        git_object_format="sha1",
        origin="local",
        repository_full_name_at_scan="acme/service",
        working_tree_dirty=True,
        source_content_hash=HASH,
        source_manifest_version="1",
        submitted_by_user_id=user_id,
        submitting_token_id=token_id,
        payload_hash=HASH,
        local_run_number=number,
        local_machine_label=machine,
    )
