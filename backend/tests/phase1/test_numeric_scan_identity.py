"""Numeric project identity contracts for scan and filesystem routes."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_scan_queue
from app.main import create_app


class _Queue:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def enqueue(self, *, project_id: int, local_path: str, options: dict) -> str:
        self.calls.append(
            {"project_id": project_id, "local_path": local_path, "options": options}
        )
        return "server-run-1"


@pytest_asyncio.fixture
async def numeric_client():
    from app.infrastructure.db.connection import get_engine
    from app.infrastructure.db.models import Base

    app = create_app()
    queue = _Queue()
    app.dependency_overrides[get_scan_queue] = lambda: queue
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, queue

    from app.infrastructure.db import connection as db_connection

    db_connection._engine = None
    db_connection._sessionmaker = None


async def _project(*, tag: str, local_path: str | None, github_repo: str | None = None) -> int:
    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.models import Project

    factory = get_sessionmaker()
    async with factory() as session:
        project = Project(
            tag=tag,
            local_path=local_path,
            github_repo=github_repo,
            github_repo_key=github_repo.casefold() if github_repo else None,
        )
        session.add(project)
        await session.commit()
        return project.id


async def test_scan_creation_and_listing_use_project_id(
    numeric_client, tmp_path: Path
) -> None:
    client, queue = numeric_client
    project_id = await _project(
        tag="checked-out",
        local_path=str(tmp_path),
        github_repo="owner/repo",
    )

    created = await client.post(
        "/api/scans",
        json={"project_id": project_id, "options": {"mode": "quick"}},
    )
    assert created.status_code == 202
    assert created.json() == {
        "run_id": "server-run-1",
        "project_id": project_id,
        "origin": "server",
        "status": "queued",
        "queued_at": created.json()["queued_at"],
    }
    assert queue.calls == [
        {
            "project_id": project_id,
            "local_path": str(tmp_path),
            "options": {"mode": "quick"},
        }
    ]

    listed = await client.get("/api/scans", params={"project_id": project_id})
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["project_id"] == project_id
    assert row["origin"] == "server"
    assert row["repository"] == "owner/repo"
    assert "project_path" not in row

    trends = await client.get("/api/trends", params={"project_id": project_id})
    assert trends.status_code == 200
    assert trends.json()["runs"] == []


async def test_scan_creation_rejects_project_without_server_checkout(
    numeric_client,
) -> None:
    client, queue = numeric_client
    project_id = await _project(
        tag="remote-only",
        local_path=None,
        github_repo="owner/remote-only",
    )

    response = await client.post("/api/scans", json={"project_id": project_id})
    assert response.status_code == 422
    assert response.json()["detail"] == "project has no available server checkout"
    assert queue.calls == []


async def test_filesystem_routes_resolve_registered_local_path(
    numeric_client, tmp_path: Path
) -> None:
    client, _queue = numeric_client
    source = tmp_path / "tests/test_example.py"
    source.parent.mkdir(parents=True)
    source.write_text("def test_example():\n    assert True\n", encoding="utf-8")
    project_id = await _project(tag="source", local_path=str(tmp_path))

    response = await client.get(
        "/api/test-source",
        params={"project_id": project_id, "name_pattern": "tests.test_example::test_example"},
    )
    assert response.status_code == 200
    assert response.json()["path"] == "tests/test_example.py"

    legacy = await client.get(
        "/api/test-source",
        params={"project_path": str(tmp_path), "name_pattern": "tests.test_example::*"},
    )
    assert legacy.status_code == 422


async def test_github_and_local_origins_share_one_project_identity(session) -> None:
    from app.api.routes.scans import list_scans
    from app.infrastructure.db.models import ApiToken, Project, Run, User
    from app.infrastructure.project_access import SYSTEM_PRINCIPAL

    now = dt.datetime.now(dt.timezone.utc)
    project = Project(
        tag="shared",
        github_repo="Owner/Repository",
        github_repo_key="owner/repository",
        github_repository_id=123456,
    )
    user = User(email="developer@example.test", role="user")
    session.add_all([project, user])
    await session.flush()
    token = ApiToken(
        id="00000000-0000-4000-8000-000000000001",
        user_id=user.id,
        label="laptop",
        label_key="laptop",
        selector="AAAAAAAAAAAAAAAA",
        secret_digest=b"x" * 32,
        scope="scans:upload",
        token_version=1,
        created_at=now,
        expires_at=now + dt.timedelta(days=90),
    )
    session.add(token)
    await session.flush()
    session.add_all(
        [
            Run(
                run_id="github-run",
                project_id=project.id,
                origin="github-actions",
                repository_full_name_at_scan="Owner/Repository",
                working_tree_dirty=False,
                commit_sha="a" * 40,
                git_object_format="sha1",
                git_branch="main",
                github_run_id=987,
                github_head_sha="a" * 40,
                status="completed",
            ),
            Run(
                run_id="local-run",
                project_id=project.id,
                origin="local",
                repository_full_name_at_scan="Owner/Repository",
                working_tree_dirty=True,
                source_content_hash="b" * 64,
                source_manifest_version="1",
                submitted_by_user_id=user.id,
                submitting_token_id=token.id,
                commit_sha="b" * 40,
                git_object_format="sha1",
                git_branch="feature/local-scan",
                local_run_number=3,
                local_machine_label="laptop",
                status="completed",
            ),
        ]
    )
    await session.commit()

    scans = await list_scans(
        principal=SYSTEM_PRINCIPAL,
        project_id=project.id,
        limit=50,
        session=session,
    )
    assert {scan.project_id for scan in scans} == {project.id}
    assert {(scan.origin, scan.git_branch) for scan in scans} == {
        ("github-actions", "main"),
        ("local", "feature/local-scan"),
    }
    local_scan = next(scan for scan in scans if scan.origin == "local")
    assert local_scan.run_number == 3
    assert local_scan.display_title == "laptop"
