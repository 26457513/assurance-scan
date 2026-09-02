"""Branch compliance grid: newest run per (catalogue snapshot, branch) wins."""
from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.infrastructure.db.models import Run
from app.main import create_app


@pytest_asyncio.fixture
async def client():
    from app.infrastructure.db.connection import get_engine
    from app.infrastructure.db.models import Base

    app = create_app()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    from app.infrastructure.db import connection as _conn
    _conn._engine = None
    _conn._sessionmaker = None


@pytest.mark.asyncio
async def test_grid_picks_newest_run_per_pair(client) -> None:
    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.models import (
        ApiToken,
        CatalogueSnapshot,
        FrState,
        Project,
        User,
    )

    factory = get_sessionmaker()
    async with factory() as session:
        project = Project(
            tag="grid", github_repo="org/grid", github_repo_key="org/grid"
        )
        user = User(email="grid@example.test", role="user")
        session.add_all((project, user))
        await session.flush()
        token = ApiToken(
            id="33333333-3333-4333-8333-333333333333",
            user_id=user.id,
            label="grid laptop",
            label_key="grid laptop",
            selector="C" * 16,
            secret_digest=b"c" * 32,
            scope="scans:upload",
            token_version=1,
            created_at=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
            expires_at=dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc),
        )
        snap = "grid-snap-1"
        session.add_all((token, CatalogueSnapshot(
            id=snap, project_id=project.id,
            catalogue_version="v1", snapshot_json="{}",
            content_hash="sha256:grid", source_branch="main",
        )))
        await session.commit()
        old = _github_run("grid-old", project.id, snap, "main", 1)
        new = _github_run("grid-new", project.id, snap, "main", 2)
        other = _github_run("grid-other", project.id, snap, "dev", 3)
        local_newer = Run(
            run_id="grid-local-private",
            project_id=project.id,
            origin="local",
            status="completed",
            git_branch="main",
            catalogue_snapshot_id=snap,
            started_at=dt.datetime(2026, 8, 4, tzinfo=dt.timezone.utc),
            submitted_by_user_id=user.id,
            submitting_token_id=token.id,
            commit_sha="f" * 40,
            git_object_format="sha1",
            working_tree_dirty=True,
            source_content_hash="f" * 64,
            source_manifest_version="1",
        )
        session.add_all([old, new, other, local_newer])
        await session.commit()  # runs must exist before the FK'd states
        session.add_all([
            FrState(fr_id="FR-1", run_id="grid-new", state="passed"),
            FrState(fr_id="FR-2", run_id="grid-new", state="failed"),
            FrState(fr_id="FR-1", run_id="grid-other", state="passed"),
        ])
        await session.commit()

    res = await client.get("/api/compliance/grid", params={"project_id": project.id})
    assert res.status_code == 200
    body = res.json()
    assert sorted(body["branches"]) == ["dev", "main"]

    main_cell = body["cells"][f"{body['versions'][0]['snapshot_id']}|main"]
    assert main_cell["run_id"] == "grid-new"  # newest wins, not the old run
    assert main_cell["ok"] == 1
    assert main_cell["gaps"] == 1

    dev_cell = body["cells"][f"{body['versions'][0]['snapshot_id']}|dev"]
    assert dev_cell["run_id"] == "grid-other"
    assert dev_cell["ok"] == 1 and dev_cell["gaps"] == 0


def _github_run(
    run_id: str,
    project_id: int,
    snapshot_id: str,
    branch: str,
    day: int,
) -> Run:
    return Run(
        run_id=run_id,
        project_id=project_id,
        origin="github-actions",
        status="completed",
        git_branch=branch,
        catalogue_snapshot_id=snapshot_id,
        started_at=dt.datetime(2026, 8, day, tzinfo=dt.timezone.utc),
        commit_sha=str(day) * 40,
        git_object_format="sha1",
        working_tree_dirty=False,
        github_run_id=day,
    )
