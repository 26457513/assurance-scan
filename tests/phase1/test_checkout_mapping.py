"""Per-user checkout mapping: own path wins, shared fallback, never other users."""
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


@pytest.mark.asyncio
async def test_lookup_order_own_then_shared(client) -> None:
    from datetime import datetime, timezone

    from server.db.connection import get_sessionmaker
    from server.db.models import ProjectCheckout
    from server.mcp.server import _lookup_checkout

    factory = get_sessionmaker()
    async with factory() as session:
        session.add(ProjectCheckout(
            user_email="", project_path="github:org/repo",
            checkout_path="/shared/fallback", updated_at=datetime.now(timezone.utc),
        ))
        session.add(ProjectCheckout(
            user_email="a@example.com", project_path="github:org/repo",
            checkout_path="/a/checkout", updated_at=datetime.now(timezone.utc),
        ))
        await session.commit()

        assert await _lookup_checkout(session, "a@example.com", "github:org/repo") == "/a/checkout"
        # Unknown user falls back to the shared mapping, not another user's.
        assert await _lookup_checkout(session, "b@example.com", "github:org/repo") == "/shared/fallback"
        assert await _lookup_checkout(session, "a@example.com", "github:org/other") is None


@pytest.mark.asyncio
async def test_save_then_overwrite(client) -> None:
    from server.db.connection import get_sessionmaker
    from server.mcp.server import build_mcp_server

    factory = get_sessionmaker()

    class FakeCtx:
        class request_context:  # noqa: N801
            class request:  # noqa: N801
                headers: dict[str, str] = {}

    # Reach the tool through the built server's tool registry
    from mcp.server.fastmcp.tools.base import Tool
    app = create_app()
    server = app.state.mcp_server if hasattr(app.state, "mcp_server") else None
    assert server is not None
    fn = server._tool_manager._tools["save_checkout_mapping"].fn  # type: ignore[attr-defined]
    res = await fn("github:org/isolated", "/x/checkout", ctx=FakeCtx())
    assert res["status"] == "saved"
    res = await fn("github:org/isolated", "/x/moved", ctx=FakeCtx())
    assert res["checkout_path"] == "/x/moved"

    from sqlalchemy import select
    from server.db.models import ProjectCheckout as PC

    async with factory() as session:
        rows = (await session.execute(select(PC).where(PC.project_path == "github:org/isolated"))).scalars().all()
        assert len(rows) == 1  # upsert, not duplicate
        assert rows[0].checkout_path == "/x/moved"
        assert rows[0].user_email == ""
