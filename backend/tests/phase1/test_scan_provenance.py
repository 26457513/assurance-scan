"""Provenance pinning tests for GET /api/scans/{run_id}.

A run must report which catalogue snapshot + mapping hash it evaluated
against, the project's current artefacts, and staleness flags.
"""
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


async def _seed(project_path: str, catalogue_versions: list[str], run_pinned_to: int | None, run_id: str):
    """Create snapshots + a run; return (run_id, latest_snapshot_hash)."""
    import datetime as dt

    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.models import Project, Run
    from app.infrastructure.db.repositories.catalogue_snapshots import CatalogueSnapshotRepository

    factory = get_sessionmaker()
    async with factory() as session:
        project = Project(tag=run_id, local_path=project_path)
        session.add(project)
        await session.flush()
        snaps = []
        repo = CatalogueSnapshotRepository(session)
        for i, version in enumerate(catalogue_versions):
            snap = await repo.store(
                project_id=project.id,
                catalogue={"schema_version": 3, "catalogue_version": version, "frs": [{"id": f"FR-T-{i}"}]},
                catalogue_version=version,
            )
            snap.created_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=i)
            snaps.append(snap)
        run = Run(
            run_id=run_id,
            project_id=project.id,
            origin="server",
            catalogue_snapshot_id=snaps[run_pinned_to].id if run_pinned_to is not None else None,
            status="completed",
        )
        session.add(run)
        await session.commit()
        return run.run_id, snaps[-1].content_hash, project.id


async def test_provenance_flags_stale_catalogue(client) -> None:
    """Run pinned to an old snapshot while a newer one exists → catalogue_stale=true."""
    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.models import Run
    from app.infrastructure.db.repositories.compliance_mappings import ComplianceMappingRepository

    run_id, latest_hash, project_id = await _seed("/proj/stale", ["v1", "v2"], run_pinned_to=0, run_id="run-stale")

    factory = get_sessionmaker()
    async with factory() as session:
        await ComplianceMappingRepository(session).upsert(
            project_id=project_id,
            content_hash="sha256:map-current",
            mapping_doc={"framework": "ASVS"},
        )

        run = await session.get(Run, run_id)
        run.mapping_hash = "sha256:map-old"
        await session.commit()

    res = await client.get(f"/api/scans/{run_id}")
    assert res.status_code == 200
    prov = res.json()["provenance"]

    assert prov["catalogue"]["version"] == "v1"
    assert prov["catalogue_stale"] is True
    assert prov["current_catalogue"]["version"] == "v2"
    assert prov["current_catalogue"]["content_hash"] == latest_hash

    assert prov["mapping_hash"] == "sha256:map-old"
    assert prov["current_mapping_hash"] == "sha256:map-current"
    assert prov["mapping_stale"] is True


async def test_provenance_current_catalogue_not_stale(client) -> None:
    """Run pinned to the latest snapshot → catalogue_stale=false, mapping unknown."""
    run_id, _, _ = await _seed("/proj/fresh", ["v1"], run_pinned_to=0, run_id="run-fresh")

    res = await client.get(f"/api/scans/{run_id}")
    assert res.status_code == 200
    prov = res.json()["provenance"]

    assert prov["catalogue_stale"] is False
    assert prov["current_catalogue"]["version"] == "v1"
    assert prov["mapping_hash"] is None
    assert prov["mapping_stale"] is None


async def test_provenance_absent_when_nothing_pinned(client) -> None:
    """Run with no catalogue and no mapping → refs null, staleness unknown."""
    run_id, _, _ = await _seed("/proj/unpinned", ["v1"], run_pinned_to=None, run_id="run-unpinned")

    res = await client.get(f"/api/scans/{run_id}")
    assert res.status_code == 200
    prov = res.json()["provenance"]

    assert prov["catalogue"] is None
    assert prov["catalogue_stale"] is None
