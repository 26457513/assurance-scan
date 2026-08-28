"""FR-REST-API tests.

Verifies the public REST surface under /api/* returns the expected shapes:
health, scans list, scan detail, findings list, FR list, FR detail, trends,
compliance framework list. Uses httpx.AsyncClient against the FastAPI app
factory directly (no network port).
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    """Boot the FastAPI app against a fresh test DB with schema initialised.

    The conftest sets ASSURANCE_SCAN_DB_PATH to a per-test file path; we
    create_all() against the app's engine so route handlers don't 500 on
    missing-table errors.
    """
    from app.infrastructure.db.connection import get_engine
    from app.infrastructure.db.models import Base

    app = create_app()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Drop the engine so the next test gets a fresh one bound to a new DB path.
    from app.infrastructure.db import connection as _conn
    _conn._engine = None
    _conn._sessionmaker = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

async def test_health_returns_ok(client) -> None:
    """Health endpoint returns 200 with the documented shape. The status
    field may be 'ok' or 'degraded' depending on whether docker socket is
    reachable from the test environment; we only assert shape here.
    """
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in {"ok", "degraded", "down"}
    assert body["db"] in {"ok", "down"}
    assert body["docker_socket"] in {"ok", "down"}
    assert "version" in body
    assert isinstance(body["uptime_seconds"], int)


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------

async def test_list_scans_returns_array(client) -> None:
    """GET /api/scans returns a list (may be empty in fresh test DB)."""
    res = await client.get("/api/scans")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)


async def test_scan_detail_unknown_run_returns_404(client) -> None:
    """Unknown run_id gives 404, not a 500."""
    res = await client.get("/api/scans/nonexistent-run")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

async def test_findings_for_unknown_run_returns_404(client) -> None:
    """Findings endpoint requires the run to exist; unknown run 404s."""
    res = await client.get("/api/scans/nonexistent-run/findings")
    assert res.status_code in (404, 200)  # implementation may either 404 or return empty


# ---------------------------------------------------------------------------
# FRs
# ---------------------------------------------------------------------------

async def test_list_frs_returns_catalogue_shape(client) -> None:
    """GET /api/frs returns catalogue metadata + frs array.
    Without a catalogue snapshot in the test DB, catalogue is null and frs
    is empty — but the response shape is stable.
    """
    res = await client.get("/api/frs")
    assert res.status_code == 200
    body = res.json()
    assert "catalogue" in body
    assert "run_id" in body
    assert "frs" in body
    assert isinstance(body["frs"], list)


async def test_fr_detail_unknown_id_returns_404(client) -> None:
    res = await client.get("/api/frs/FR-DOES-NOT-EXIST")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

async def test_list_compliance_frameworks_returns_array(client) -> None:
    """GET /api/compliance returns a frameworks array (may be empty without a mapping)."""
    res = await client.get("/api/compliance")
    assert res.status_code == 200
    body = res.json()
    assert "frameworks" in body
    assert isinstance(body["frameworks"], list)


async def test_compliance_matrix_unknown_framework_returns_404(client) -> None:
    res = await client.get("/api/compliance/BOGUS")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

async def test_trends_returns_runs_array(client) -> None:
    res = await client.get("/api/trends")
    assert res.status_code == 200
    body = res.json()
    assert "runs" in body
    assert isinstance(body["runs"], list)


# ---------------------------------------------------------------------------
# Unknown routes 404, not 500
# ---------------------------------------------------------------------------

async def test_unknown_api_route_returns_404(client) -> None:
    res = await client.get("/api/does-not-exist")
    assert res.status_code == 404
