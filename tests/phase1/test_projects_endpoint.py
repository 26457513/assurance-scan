"""Projects registry + pack-content endpoints."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from server.main import create_app


@pytest_asyncio.fixture
async def client():
    from server.db.connection import get_engine
    from server.db.models import Base

    app = create_app()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    from server.db import connection as _conn
    _conn._engine = None
    _conn._sessionmaker = None


async def _seed_runs(project_path: str, n: int) -> None:
    from server.db.connection import get_sessionmaker
    from server.db.models import Run

    factory = get_sessionmaker()
    async with factory() as session:
        for i in range(n):
            session.add(Run(run_id=f"run-{project_path}-{i}", project_path=project_path, status="completed"))
        await session.commit()


async def test_projects_lists_paths_with_counts(client) -> None:
    await _seed_runs("/proj/alpha", 2)
    await _seed_runs("/proj/beta", 1)

    res = await client.get("/api/projects")
    assert res.status_code == 200
    projects = res.json()["projects"]
    by_path = {p["project_path"]: p for p in projects}
    assert by_path["/proj/alpha"]["run_count"] == 2
    assert by_path["/proj/beta"]["run_count"] == 1
    assert by_path["/proj/alpha"]["has_catalogue"] is False


async def test_projects_includes_catalogue_only_projects(client) -> None:
    from server.db.connection import get_sessionmaker
    from server.db.repositories.catalogue_snapshots import CatalogueSnapshotRepository

    factory = get_sessionmaker()
    async with factory() as session:
        await CatalogueSnapshotRepository(session).store(
            project_path="/proj/never-scanned",
            catalogue={"schema_version": 3, "frs": []},
            catalogue_version=None,
        )
        await session.commit()

    res = await client.get("/api/projects")
    by_path = {p["project_path"]: p for p in res.json()["projects"]}
    assert "/proj/never-scanned" in by_path
    assert by_path["/proj/never-scanned"]["run_count"] == 0
    assert by_path["/proj/never-scanned"]["has_catalogue"] is True


async def test_pack_content_endpoint(client) -> None:
    res = await client.get("/api/compliance/packs/asvs-5.0.0.json")
    assert res.status_code == 200
    assert "rows" in res.json()

    traversal = await client.get("/api/compliance/packs/..%2F..%2Fetc%2Fpasswd.json")
    assert traversal.status_code in (400, 404)

    missing = await client.get("/api/compliance/packs/nope-1.0.0.json")
    assert missing.status_code == 404
