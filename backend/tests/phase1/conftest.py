"""Pytest fixtures for Phase 1 tests.

In-memory SQLite, alembic-stamped schema, isolated per test function.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set config env BEFORE importing server modules so they pick up the test paths.
_DB_PATH = Path("/tmp") / f"assurance-scan-test-{os.getpid()}.db"
if _DB_PATH.exists():
    _DB_PATH.unlink()

os.environ["ASSURANCE_SCAN_DB_PATH"] = str(_DB_PATH)
os.environ["ASSURANCE_SCAN_HOST"] = "127.0.0.1"
os.environ["ASSURANCE_SCAN_PORT"] = "0"  # not used by tests


def pytest_sessionfinish() -> None:
    """Remove process-local SQLite files without colliding with parallel gates."""
    for suffix in ("", "-shm", "-wal"):
        (_DB_PATH.parent / f"{_DB_PATH.name}{suffix}").unlink(missing_ok=True)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def engine():
    """Per-test async engine against an in-memory SQLite DB."""
    from app.infrastructure.db.models import Base

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
def sample_v2_catalogue() -> dict:
    """A minimal v2 catalogue exercising required_evidence shape."""
    return {
        "schema_version": 2,
        "project": "test-project",
        "catalogue_version": "2026-08-07T00:00:00Z",
        "frs": [
            {
                "id": "FR-001",
                "title": "No eval",
                "description": "Source must not use eval.",
                "required_evidence": {
                    "none_of": [
                        {
                            "type": "scanner-result",
                            "source_kind": "semgrep",
                            "rule_id": "eval-detected",
                        }
                    ]
                },
                "satisfies": ["ASVS:v5.0.0-5.3.4"],
                "depends_on": [],
            }
        ],
        "na_rows": [],
    }


@pytest.fixture
def sample_v1_catalogue_with_tbts() -> dict:
    """A v1 catalogue with FRs + TBTs, for migration tests."""
    return {
        "schema_version": 1,
        "project": "legacy-project",
        "frs": [
            {
                "id": "FR-001",
                "title": "Session management",
                "description": "Sessions must be managed.",
                "satisfies": ["ASVS:v5.0.0-5.1.1"],
            }
        ],
        "tbts": [
            {
                "id": "TBT-001",
                "title": "Session timeout test",
                "description": "Session must time out.",
                "parent": "FR-001",
                "required_evidence": {
                    "all_of": [
                        {
                            "type": "unit-test",
                            "name_pattern": "tests/test_session.py::test_timeout",
                            "expected_result": "pass",
                        }
                    ]
                },
                "satisfies": ["ASVS:v5.0.0-5.1.2"],
            }
        ],
    }
