"""Version-history endpoints: catalogue snapshots, mapping snapshots, packs."""
from __future__ import annotations

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
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    from app.infrastructure.db import connection as _conn
    _conn._engine = None
    _conn._sessionmaker = None


async def _seed_catalogue(project_path: str, version: str) -> str:
    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.repositories.catalogue_snapshots import CatalogueSnapshotRepository

    factory = get_sessionmaker()
    async with factory() as session:
        snap = await CatalogueSnapshotRepository(session).store(
            project_path=project_path,
            catalogue={"schema_version": 3, "catalogue_version": version, "frs": []},
            catalogue_version=version,
        )
        await session.commit()
        return snap.content_hash


_MAPPING_V1 = {
    "schema_version": 1,
    "project": "proj-ver",
    "mappings": [
        {"ruleset": "asvs", "version": "5.0.0", "row": "V1.1.1", "satisfied_by": ["FR-A"], "appropriate": True}
    ],
}


async def test_mapping_snapshot_pins_targets_and_lists(client) -> None:
    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.repositories.compliance_mappings import ComplianceMappingRepository

    project = "/proj/versions"
    catalogue_hash = await _seed_catalogue(project, "v1")

    factory = get_sessionmaker()
    async with factory() as session:
        repo = ComplianceMappingRepository(session)
        await repo.upsert(project_path=project, content_hash="sha256:map-1", mapping_doc=_MAPPING_V1)
        await session.commit()

    res = await client.get("/api/mappings/versions", params={"project_path": project})
    assert res.status_code == 200
    versions = res.json()["versions"]
    assert len(versions) == 1
    assert versions[0]["content_hash"] == "sha256:map-1"
    assert versions[0]["catalogue_content_hash"] == catalogue_hash
    assert versions[0]["packs"] == [{"ruleset": "asvs", "version": "5.0.0"}]

    # A second mapping accumulates history instead of replacing it.
    doc2 = {**_MAPPING_V1, "mappings": _MAPPING_V1["mappings"] + [
        {"ruleset": "asvs", "version": "5.0.0", "row": "V1.1.2", "satisfied_by": ["FR-B"], "appropriate": True}
    ]}
    async with factory() as session:
        await ComplianceMappingRepository(session).upsert(
            project_path=project, content_hash="sha256:map-2", mapping_doc=doc2
        )
        await session.commit()

    res = await client.get("/api/mappings/versions", params={"project_path": project})
    assert [v["content_hash"] for v in res.json()["versions"]] == ["sha256:map-2", "sha256:map-1"]


async def test_catalogue_versions_listed_newest_first(client) -> None:
    import datetime as dt

    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.repositories.catalogue_snapshots import CatalogueSnapshotRepository

    project = "/proj/catver"
    await _seed_catalogue(project, "v1")
    factory = get_sessionmaker()
    async with factory() as session:
        snap = await CatalogueSnapshotRepository(session).store(
            project_path=project,
            catalogue={"schema_version": 3, "catalogue_version": "v2", "frs": []},
            catalogue_version="v2",
        )
        snap.created_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=5)
        await session.commit()
        newest_id = snap.id

    res = await client.get("/api/catalogue/versions", params={"project_path": project})
    assert res.status_code == 200
    versions = res.json()["versions"]
    assert len(versions) == 2
    assert versions[0]["snapshot_id"] == newest_id
    assert versions[0]["version"] == "v2"


async def test_frs_accepts_snapshot_id(client) -> None:
    project = "/proj/frsnap"
    await _seed_catalogue(project, "only-v")

    res = await client.get("/api/frs", params={"project_path": project})
    assert res.status_code == 200
    snap_id = res.json()["catalogue"]["snapshot_id"]
    assert res.json()["catalogue"]["catalogue_version"] == "only-v"

    by_id = await client.get("/api/frs", params={"snapshot_id": snap_id})
    assert by_id.status_code == 200
    assert by_id.json()["catalogue"]["snapshot_id"] == snap_id


async def test_compliance_matrix_by_mapping_hash(client) -> None:
    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.repositories.compliance_mappings import ComplianceMappingRepository

    project = "/proj/matrix"
    await _seed_catalogue(project, "v1")
    factory = get_sessionmaker()
    async with factory() as session:
        await ComplianceMappingRepository(session).upsert(
            project_path=project, content_hash="sha256:map-1", mapping_doc=_MAPPING_V1
        )
        await session.commit()

    res = await client.get(
        "/api/compliance/asvs", params={"mapping_hash": "sha256:map-1"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["mapping_hash"] == "sha256:map-1"
    assert [r["row_id"] for r in body["rows"]] == ["V1.1.1"]

    missing = await client.get(
        "/api/compliance/asvs", params={"mapping_hash": "sha256:nope"}
    )
    assert missing.status_code == 404


async def test_compliance_packs_inventory(client) -> None:
    res = await client.get("/api/compliance/packs")
    assert res.status_code == 200
    packs = res.json()["packs"]
    asvs = [p for p in packs if p["id"] == "asvs"]
    assert any(p["version"] == "5.0.0" for p in asvs)
