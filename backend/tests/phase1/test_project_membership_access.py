"""Project membership is the mandatory backend visibility boundary."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi import FastAPI, HTTPException

from app.api.routes.projects import list_projects
from app.api.routes.scans import get_scan, list_scans
from app.api.routes.trends import trends
from app.config import load_settings
from app.infrastructure.db.models import (
    ApiToken,
    GithubAccount,
    GithubAppInstallation,
    GithubInstallationRepository,
    Project,
    ProjectMembership,
    Run,
    User,
)
from app.infrastructure.project_access import (
    ProjectAccessPrincipal,
    CURRENT_PROJECT_ACCESS,
    require_project,
    require_run,
    sync_github_app_memberships,
)
from app.modules.atomic.access.github_membership_projection import (
    GithubProjectPermission,
    GithubRepositoryEntitlement,
)
from app.modules.atomic.access.run_visibility import RunVisibilityContext, can_view_run
from app.secrets import encrypt


async def _seed(session):
    user = User(email="member@example.test", role="user")
    first = Project(tag="first", local_path="/projects/first")
    second = Project(tag="second", local_path="/projects/second")
    session.add_all((user, first, second))
    await session.flush()
    session.add(
        ProjectMembership(
            user_id=user.id,
            project_id=first.id,
            permission="view",
            source="github_app",
            verified_at=dt.datetime.now(dt.timezone.utc),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5),
        )
    )
    session.add_all(
        (
            Run(
                run_id="first-run",
                project_id=first.id,
                origin="server",
                status="completed",
                started_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
            ),
            Run(
                run_id="second-run",
                project_id=second.id,
                origin="server",
                status="completed",
                started_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
            ),
        )
    )
    await session.commit()
    return user, first, second


async def test_dashboard_and_direct_run_access_are_membership_scoped(session) -> None:
    user, first, second = await _seed(session)
    principal = ProjectAccessPrincipal(user_id=user.id, role="user")

    projects = await list_projects(principal=principal, session=session)
    scans = await list_scans(
        principal=principal, project_id=None, limit=50, session=session
    )

    assert [row["id"] for row in projects["projects"]] == [first.id]
    assert [scan.run_id for scan in scans] == ["first-run"]
    with pytest.raises(HTTPException) as denied:
        await get_scan("second-run", principal=principal, session=session)
    assert denied.value.status_code == 404
    assert await require_project(session, principal, second.id) is None


async def test_permission_levels_and_admin_do_not_bypass_entitlement(session) -> None:
    user, first, second = await _seed(session)
    principal = ProjectAccessPrincipal(user_id=user.id, role="user")
    admin = ProjectAccessPrincipal(user_id=user.id, role="admin")

    assert await require_project(session, principal, first.id, "view") is not None
    assert await require_project(session, principal, first.id, "upload") is None
    assert await require_project(session, admin, second.id, "manage") is None


async def test_local_runs_and_project_statistics_are_private_to_submitter(
    session,
    session_factory,
    monkeypatch,
) -> None:
    owner, project, _ = await _seed(session)
    viewer = User(email="viewer@example.test", role="user")
    session.add(viewer)
    await session.flush()
    session.add(
        ProjectMembership(
            user_id=viewer.id,
            project_id=project.id,
            permission="view",
            source="github_app",
            verified_at=dt.datetime.now(dt.timezone.utc),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5),
        )
    )
    owner_token = ApiToken(
        id="11111111-1111-4111-8111-111111111111",
        user_id=owner.id,
        label="owner laptop",
        label_key="owner laptop",
        selector="A" * 16,
        secret_digest=b"a" * 32,
        scope="scans:upload",
        token_version=1,
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        expires_at=dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc),
    )
    viewer_token = ApiToken(
        id="22222222-2222-4222-8222-222222222222",
        user_id=viewer.id,
        label="viewer laptop",
        label_key="viewer laptop",
        selector="B" * 16,
        secret_digest=b"b" * 32,
        scope="scans:upload",
        token_version=1,
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        expires_at=dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc),
    )
    session.add_all((owner_token, viewer_token))
    await session.flush()
    session.add_all(
        (
            Run(
                run_id="github-visible",
                project_id=project.id,
                origin="github-actions",
                status="completed",
                started_at=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
                commit_sha="a" * 40,
                git_object_format="sha1",
                working_tree_dirty=False,
                github_run_id=101,
                git_branch="main",
            ),
            Run(
                run_id="owner-local-private",
                project_id=project.id,
                origin="local",
                submitted_by_user_id=owner.id,
                submitting_token_id=owner_token.id,
                status="completed",
                started_at=dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc),
                commit_sha="b" * 40,
                git_object_format="sha1",
                working_tree_dirty=True,
                source_content_hash="b" * 64,
                source_manifest_version="1",
                findings_json='{"findings": [], "marker": "owner"}',
                git_branch="owner-private",
            ),
            Run(
                run_id="viewer-local-visible",
                project_id=project.id,
                origin="local",
                submitted_by_user_id=viewer.id,
                submitting_token_id=viewer_token.id,
                status="completed",
                started_at=dt.datetime(2026, 1, 4, tzinfo=dt.timezone.utc),
                commit_sha="c" * 40,
                git_object_format="sha1",
                working_tree_dirty=False,
                source_content_hash="c" * 64,
                source_manifest_version="1",
                findings_json='{"findings": [], "marker": "viewer"}',
                git_branch="viewer-feature",
            ),
        )
    )
    await session.commit()
    principal = ProjectAccessPrincipal(user_id=viewer.id, role="user")

    scans = await list_scans(
        principal=principal, project_id=project.id, limit=50, session=session
    )
    projects = await list_projects(principal=principal, session=session)

    assert [scan.run_id for scan in scans] == [
        "viewer-local-visible",
        "github-visible",
        "first-run",
    ]
    assert projects["projects"][0]["run_count"] == 3
    assert projects["projects"][0]["last_scan_at"] == "2026-01-04T00:00:00"
    assert await require_run(session, principal, "owner-local-private") is None
    with pytest.raises(HTTPException) as denied:
        await get_scan("owner-local-private", principal=principal, session=session)
    assert denied.value.status_code == 404

    trend_result = await trends(
        principal=principal,
        project_id=project.id,
        limit=20,
        branch=None,
        session=session,
    )
    assert [row["run_id"] for row in trend_result["runs"]] == [
        "github-visible",
        "viewer-local-visible",
    ]
    assert trend_result["branches"] == ["main", "viewer-feature"]

    limited_trend = await trends(
        principal=principal,
        project_id=project.id,
        limit=1,
        branch=None,
        session=session,
    )
    assert len(limited_trend["runs"]) == 1
    assert limited_trend["branches"] == ["main", "viewer-feature"]

    branch_trend = await trends(
        principal=principal,
        project_id=project.id,
        limit=20,
        branch="viewer-feature",
        session=session,
    )
    assert [row["run_id"] for row in branch_trend["runs"]] == [
        "viewer-local-visible"
    ]

    monkeypatch.setattr("app.mcp.server.get_sessionmaker", lambda: session_factory)
    from app.mcp.server import build_mcp_server

    mcp = build_mcp_server(FastAPI())
    token = CURRENT_PROJECT_ACCESS.set(principal)
    try:
        mcp_scans = await mcp._tool_manager._tools["list_scans"].fn(limit=50)
        direct_private = await mcp._tool_manager._tools["get_findings"].fn(
            run_id="owner-local-private"
        )
        latest = await mcp._tool_manager._tools["get_project_findings"].fn(
            project_id=project.id,
            severity=None,
        )
    finally:
        CURRENT_PROJECT_ACCESS.reset(token)

    assert {row["run_id"] for row in mcp_scans["scans"]} == {
        "first-run",
        "github-visible",
        "viewer-local-visible",
    }
    assert direct_private == {"error": "not_found", "run_id": "owner-local-private"}
    assert latest["run_id"] == "viewer-local-visible"
    assert latest["marker"] == "viewer"


def test_run_visibility_policy_reserves_bypass_for_internal_system() -> None:
    assert can_view_run(RunVisibilityContext(None, "local", 99))
    assert can_view_run(RunVisibilityContext(7, "github-actions", None))
    assert can_view_run(RunVisibilityContext(7, "local", 7))
    assert not can_view_run(RunVisibilityContext(7, "local", 8))


async def test_github_app_refresh_is_installation_scoped_and_fails_closed(
    session, monkeypatch
) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "membership-test-key")
    monkeypatch.setenv("GITHUB_APP_ACCESS_ENABLED", "true")
    settings = load_settings()
    user = User(email="app-member@example.test", role="user")
    project = Project(
        tag="github-424242",
        github_repo="Example/installed",
        github_repo_key="example/installed",
        github_repository_id=424242,
    )
    session.add_all((user, project))
    await session.flush()
    session.add_all(
        (
            GithubAccount(
                user_id=user.id,
                github_user_id=583231,
                encrypted_user_token=encrypt("user-token", settings.token_encryption_key),
                token_expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
            ),
            GithubAppInstallation(
                github_installation_id=9001,
                github_owner_id=26457513,
                owner_login_at_last_verify="example",
                account_type="organization",
                repository_selection="selected",
                created_at=dt.datetime.now(dt.timezone.utc),
                updated_at=dt.datetime.now(dt.timezone.utc),
            ),
            GithubInstallationRepository(
                github_installation_id=9001,
                github_repository_id=424242,
                project_id=project.id,
                repository_full_name="Example/installed",
                github_owner_id=26457513,
                default_branch="main",
                visibility="private",
                archived=False,
                disabled=False,
                repository_verified_at=dt.datetime.now(dt.timezone.utc),
                enabled_at=dt.datetime.now(dt.timezone.utc),
                updated_at=dt.datetime.now(dt.timezone.utc),
            ),
        )
    )
    user_id = user.id
    project_id = project.id
    await session.commit()
    await session.refresh(user)
    principal = ProjectAccessPrincipal(user_id=user_id, role="user")
    monkeypatch.setattr(
        "app.infrastructure.project_access.GithubAppUserEntitlementClient.fetch",
        lambda _client, _token: (
            GithubRepositoryEntitlement(
                github_installation_id=9001,
                github_repository_id=424242,
                permission=GithubProjectPermission.VIEW,
            ),
        ),
    )

    assert await sync_github_app_memberships(session, user_id, settings, force=True)
    assert await require_project(session, principal, project_id) is not None

    monkeypatch.setattr(
        "app.infrastructure.project_access.GithubAppUserEntitlementClient.fetch",
        lambda _client, _token: (
            GithubRepositoryEntitlement(
                github_installation_id=9002,
                github_repository_id=424242,
                permission=GithubProjectPermission.MANAGE,
            ),
        ),
    )
    assert await sync_github_app_memberships(session, user_id, settings, force=True)
    assert await require_project(session, principal, project_id) is None

    monkeypatch.setattr(
        "app.infrastructure.project_access.GithubAppUserEntitlementClient.fetch",
        lambda _client, _token: (
            GithubRepositoryEntitlement(
                github_installation_id=9001,
                github_repository_id=424242,
                permission=GithubProjectPermission.VIEW,
            ),
        ),
    )
    assert await sync_github_app_memberships(session, user_id, settings, force=True)
    assert await require_project(session, principal, project_id) is not None

    def unavailable(_client, _token):
        raise RuntimeError("GitHub unavailable")

    monkeypatch.setattr(
        "app.infrastructure.project_access.GithubAppUserEntitlementClient.fetch",
        unavailable,
    )
    assert not await sync_github_app_memberships(session, user_id, settings, force=True)
    assert await require_project(session, principal, project_id) is None
