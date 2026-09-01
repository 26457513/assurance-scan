"""Project membership is the mandatory backend visibility boundary."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes.projects import list_projects
from app.api.routes.scans import get_scan, list_scans
from app.config import load_settings
from app.infrastructure.db.models import (
    GithubAccount,
    Project,
    ProjectMembership,
    Run,
    User,
)
from app.infrastructure.project_access import (
    ACCESS_TTL,
    ProjectAccessPrincipal,
    require_project,
    sync_github_memberships,
)
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
            source="manual",
            verified_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    session.add_all(
        (
            Run(run_id="first-run", project_id=first.id, origin="server", status="completed"),
            Run(run_id="second-run", project_id=second.id, origin="server", status="completed"),
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


async def test_permission_levels_and_admin_override(session) -> None:
    user, first, second = await _seed(session)
    principal = ProjectAccessPrincipal(user_id=user.id, role="user")
    admin = ProjectAccessPrincipal(user_id=user.id, role="admin")

    assert await require_project(session, principal, first.id, "view") is not None
    assert await require_project(session, principal, first.id, "upload") is None
    assert await require_project(session, admin, second.id, "manage") is not None


async def test_expired_github_grant_fails_closed_while_manual_grant_remains(session) -> None:
    user, first, second = await _seed(session)
    principal = ProjectAccessPrincipal(user_id=user.id, role="user")
    session.add(
        ProjectMembership(
            user_id=user.id,
            project_id=second.id,
            permission="manage",
            source="github",
            verified_at=dt.datetime.now(dt.timezone.utc) - ACCESS_TTL - dt.timedelta(seconds=1),
        )
    )
    await session.commit()

    assert await require_project(session, principal, first.id) is not None
    assert await require_project(session, principal, second.id) is None


async def test_github_sync_replaces_grants_and_maps_repository_permissions(
    session, monkeypatch
) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "membership-test-key")
    settings = load_settings()
    user = User(email="github@example.test", role="user")
    projects = [
        Project(
            tag=name,
            github_repo=f"Example/{name}",
            github_repo_key=f"example/{name}",
        )
        for name in ("viewer", "uploader", "manager", "removed")
    ]
    session.add_all((user, *projects))
    await session.flush()
    session.add(
        GithubAccount(
            email=user.email,
            login="github-user",
            token_encrypted=encrypt("github-token", settings.token_encryption_key),
        )
    )
    session.add(
        ProjectMembership(
            user_id=user.id,
            project_id=projects[3].id,
            permission="manage",
            source="github",
        )
    )
    await session.commit()

    monkeypatch.setattr(
        "app.infrastructure.project_access.GitHubClient.user_repositories",
        lambda _client: [
            {"full_name": "Example/viewer", "permissions": {"pull": True}},
            {"full_name": "Example/uploader", "permissions": {"push": True}},
            {"full_name": "Example/manager", "permissions": {"admin": True}},
        ],
    )

    assert await sync_github_memberships(session, user, settings, force=True)
    memberships = (
        await session.execute(
            select(ProjectMembership)
            .where(
                ProjectMembership.user_id == user.id,
                ProjectMembership.source == "github",
            )
            .order_by(ProjectMembership.project_id)
        )
    ).scalars().all()
    assert [(row.project_id, row.permission) for row in memberships] == [
        (projects[0].id, "view"),
        (projects[1].id, "upload"),
        (projects[2].id, "manage"),
    ]
