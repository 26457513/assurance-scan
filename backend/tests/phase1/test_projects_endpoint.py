"""Project registry and compliance-pack HTTP contracts."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    from app.infrastructure.db.connection import get_engine
    from app.infrastructure.db.models import Base

    app = create_app()
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http_client:
        yield http_client

    from app.infrastructure.db import connection

    await engine.dispose()
    connection._engine = None
    connection._sessionmaker = None


async def _seed_project(tag: str, run_count: int = 0) -> int:
    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.models import Project, Run

    async with get_sessionmaker()() as session:
        project = Project(tag=tag, local_path=f"/projects/{tag}")
        session.add(project)
        await session.flush()
        session.add_all(
            Run(
                run_id=f"{tag}-{index}",
                project_id=project.id,
                origin="server",
                status="completed",
            )
            for index in range(run_count)
        )
        await session.commit()
        return project.id


async def test_projects_lists_registered_ids_with_counts(client) -> None:
    alpha_id = await _seed_project("alpha", 2)
    beta_id = await _seed_project("beta", 1)

    response = await client.get("/api/projects")
    assert response.status_code == 200
    by_id = {project["id"]: project for project in response.json()["projects"]}
    assert by_id[alpha_id]["run_count"] == 2
    assert by_id[beta_id]["run_count"] == 1
    assert by_id[alpha_id]["has_catalogue"] is False


async def test_projects_includes_registered_catalogue_only_project(client) -> None:
    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.repositories.catalogue_snapshots import (
        CatalogueSnapshotRepository,
    )

    project_id = await _seed_project("never-scanned")
    async with get_sessionmaker()() as session:
        await CatalogueSnapshotRepository(session).store(
            project_id=project_id,
            catalogue={"schema_version": 3, "frs": []},
            catalogue_version=None,
        )
        await session.commit()

    by_id = {
        project["id"]: project
        for project in (await client.get("/api/projects")).json()["projects"]
    }
    assert by_id[project_id]["run_count"] == 0
    assert by_id[project_id]["has_catalogue"] is True


async def test_pack_content_endpoint(client) -> None:
    response = await client.get("/api/compliance/packs/asvs-5.0.0.json")
    assert response.status_code == 200
    assert "rows" in response.json()
    traversal = await client.get(
        "/api/compliance/packs/..%2F..%2Fetc%2Fpasswd.json"
    )
    assert traversal.status_code in (400, 404)
    assert (await client.get("/api/compliance/packs/nope-1.0.0.json")).status_code == 404


async def test_delete_project_tombstones_identity_and_deletes_runs(client) -> None:
    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.models import Project, Run

    response = await client.post(
        "/api/projects",
        json={"tag": "gone", "local_path": None, "github_repo": "someone/gone"},
    )
    assert response.status_code == 200
    project_id = response.json()["id"]
    async with get_sessionmaker()() as session:
        session.add(
            Run(
                run_id="gone-1",
                project_id=project_id,
                origin="server",
                status="completed",
            )
        )
        await session.commit()

    assert (await client.delete(f"/api/projects/{project_id}")).status_code == 200
    async with get_sessionmaker()() as session:
        assert (await session.execute(select(Run))).scalars().all() == []
        project = await session.get(Project, project_id)
        assert project is not None and project.hidden is True
    assert (await client.get("/api/projects")).json()["projects"] == []

    duplicate = await client.post(
        "/api/projects",
        json={"tag": "gone", "local_path": None, "github_repo": "someone/gone"},
    )
    assert duplicate.status_code == 409
