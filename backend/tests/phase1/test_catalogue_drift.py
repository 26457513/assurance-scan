"""Drift-check endpoint tests.

Verifies referential drift classification: missing implemented_by files,
unresolved test name_patterns (including glob patterns), and that existing
refs/patterns pass. Uses a throwaway project dir; not a git repo, so commit
fields are null / code_moved None.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client(tmp_path):
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


async def test_drift_classifies_missing_refs_and_patterns(client, tmp_path) -> None:
    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.models import Project
    from app.infrastructure.db.repositories.catalogue_snapshots import CatalogueSnapshotRepository

    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/app/service.py").write_text("x = 1\n")
    (tmp_path / "tests/unit/sub").mkdir(parents=True)
    (tmp_path / "tests/unit/test_real.py").write_text("def test_ok():\n    assert True\n")
    (tmp_path / "tests/unit/sub/test_glob.py").write_text("def test_ok():\n    assert True\n")
    # Test rootdir below the project root (e.g. backend/): pattern omits the prefix.
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/tests/test_nested.py").write_text("def test_ok():\n    assert True\n")

    project_path = str(tmp_path)
    catalogue = {
        "schema_version": 3,
        "catalogue_version": "test-v1",
        "frs": [
            {
                "id": "FR-OK",
                "title": "clean",
                "description": "all refs resolve",
                "implemented_by": [{"kind": "file", "ref": "backend/app/service.py"}],
                "tests": [{"id": "t-ok", "type": "unit-test", "name_pattern": "tests.unit.test_real::*"}],
            },
            {
                "id": "FR-MISSING-REF",
                "title": "gone file",
                "description": "references a deleted file",
                "implemented_by": [{"kind": "file", "ref": "gone/old.py"}],
                "tests": [],
            },
            {
                "id": "FR-MISSING-TEST",
                "title": "gone test",
                "description": "test file no longer exists",
                "implemented_by": [],
                "tests": [{"id": "t-gone", "type": "unit-test", "name_pattern": "tests.unit.test_gone::*"}],
            },
            {
                "id": "FR-GLOB",
                "title": "glob pattern",
                "description": "wildcard name_pattern resolves via glob",
                "implemented_by": [],
                "tests": [{"id": "t-glob", "type": "unit-test", "name_pattern": "tests.unit.*.test_glob::*"}],
            },
            {
                "id": "FR-NESTED",
                "title": "nested rootdir",
                "description": "pattern rooted at backend/ resolves via recursive search",
                "implemented_by": [],
                "tests": [{"id": "t-nested", "type": "unit-test", "name_pattern": "tests.test_nested::*"}],
            },
        ],
    }

    factory = get_sessionmaker()
    async with factory() as session:
        project = Project(tag="drift", local_path=project_path)
        session.add(project)
        await session.flush()
        await CatalogueSnapshotRepository(session).store(
            project_id=project.id,
            catalogue=catalogue,
            catalogue_version="test-v1",
        )
        await session.commit()

        project_id = project.id

    res = await client.get("/api/catalogue/drift", params={"project_id": project_id})
    assert res.status_code == 200
    body = res.json()

    assert body["catalogue_version"] == "test-v1"
    assert [m["fr_id"] for m in body["missing_files"]] == ["FR-MISSING-REF"]
    assert body["missing_files"][0]["ref"] == "gone/old.py"
    assert [u["fr_id"] for u in body["unresolved_patterns"]] == ["FR-MISSING-TEST"]
    assert set(body["drifted_fr_ids"]) == {"FR-MISSING-REF", "FR-MISSING-TEST"}
    assert body["snapshot_commit"] is None
    assert body["code_moved"] is None


async def test_drift_unknown_project_404(client, tmp_path) -> None:
    res = await client.get("/api/catalogue/drift", params={"project_id": 999_999})
    assert res.status_code == 404
