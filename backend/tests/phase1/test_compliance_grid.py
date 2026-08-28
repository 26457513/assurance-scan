"""Branch compliance grid: newest run per (catalogue snapshot, branch) wins."""
from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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
    from app.infrastructure.db.models import CatalogueSnapshot, FrState, Project, Run

    factory = get_sessionmaker()
    async with factory() as session:
        project = Project(
            tag="grid", github_repo="org/grid", github_repo_key="org/grid"
        )
        session.add(project)
        await session.flush()
        snap = "grid-snap-1"
        session.add(CatalogueSnapshot(
            id=snap, project_id=project.id,
            catalogue_version="v1", snapshot_json="{}",
            content_hash="sha256:grid", source_branch="main",
        ))
        await session.commit()
        old = Run(run_id="grid-old", project_id=project.id, origin="server", status="completed",
                  git_branch="main", catalogue_snapshot_id=snap,
                  started_at=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc))
        new = Run(run_id="grid-new", project_id=project.id, origin="server", status="completed",
                  git_branch="main", catalogue_snapshot_id=snap,
                  started_at=dt.datetime(2026, 8, 2, tzinfo=dt.timezone.utc))
        other = Run(run_id="grid-other", project_id=project.id, origin="server", status="completed",
                    git_branch="dev", catalogue_snapshot_id=snap,
                    started_at=dt.datetime(2026, 8, 3, tzinfo=dt.timezone.utc))
        session.add_all([old, new, other])
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
