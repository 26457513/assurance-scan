"""Per-user MCP token generation stores a hash, never the plaintext."""
from __future__ import annotations

import hashlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Request

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
async def test_rotate_stores_hash_not_plaintext(client) -> None:
    from sqlalchemy import select

    from server.api.routes.gh_tokens import rotate_mcp_token
    from server.db.connection import get_sessionmaker
    from server.db.models import User

    factory = get_sessionmaker()
    async with factory() as session:
        user = User(email="mcp-test@example.com", role="user")
        session.add(user)
        await session.commit()

        res = await rotate_mcp_token(
            request=Request("POST", "http://test:8742/api/users/me/mcp-token"),
            user=user,
            session=session,
        )
        assert res["token"]
        assert "Bearer " in res["command"]
        assert "http://test:8742/mcp" in res["command"]

        row = (await session.execute(select(User).where(User.email == user.email))).scalars().one()
        assert row.mcp_token_hash == hashlib.sha256(res["token"].encode()).hexdigest()
        assert row.mcp_token_hash != res["token"]
        assert row.mcp_token_generated_at is not None
