"""Per-user checkout mappings use durable user and project identities."""
from __future__ import annotations

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
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    from app.infrastructure.db import connection as _conn
    _conn._engine = None
    _conn._sessionmaker = None


@pytest.mark.asyncio
async def test_lookup_is_scoped_to_user_and_project_ids(client) -> None:
    from datetime import datetime, timezone

    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.models import Project, ProjectCheckout, User
    from app.mcp.server import _lookup_checkout

    factory = get_sessionmaker()
    async with factory() as session:
        alice = User(email="a@example.com", role="user")
        bob = User(email="b@example.com", role="user")
        project = Project(
            tag="org-repo",
            github_repo="org/repo",
            github_repo_key="org/repo",
        )
        other = Project(
            tag="org-other",
            github_repo="org/other",
            github_repo_key="org/other",
        )
        session.add_all([alice, bob, project, other])
        await session.flush()
        session.add(ProjectCheckout(
            user_id=alice.id, project_id=project.id,
            checkout_path="/a/checkout", updated_at=datetime.now(timezone.utc),
        ))
        await session.commit()

        assert await _lookup_checkout(session, alice.id, project.id) == "/a/checkout"
        assert await _lookup_checkout(session, bob.id, project.id) is None
        assert await _lookup_checkout(session, alice.id, other.id) is None


@pytest.mark.asyncio
async def test_save_then_overwrite(client) -> None:
    import hashlib

    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.models import Project, User

    factory = get_sessionmaker()
    token = "mcp-test-token"
    async with factory() as session:
        user = User(
            email="save@example.com",
            role="user",
            mcp_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        project = Project(
            tag="isolated",
            github_repo="org/isolated",
            github_repo_key="org/isolated",
        )
        session.add_all([user, project])
        await session.commit()
        project_id = project.id

    class FakeCtx:
        class request_context:  # noqa: N801
            class request:  # noqa: N801
                headers = {"authorization": f"Bearer {token}"}

    # Reach the tool through the built server's tool registry
    app = create_app()
    server = app.state.mcp_server if hasattr(app.state, "mcp_server") else None
    assert server is not None
    fn = server._tool_manager._tools["save_checkout_mapping"].fn  # type: ignore[attr-defined]
    res = await fn(project_id, "/x/checkout", ctx=FakeCtx())
    assert res["status"] == "saved"
    res = await fn(project_id, "/x/moved", ctx=FakeCtx())
    assert res["checkout_path"] == "/x/moved"

    from sqlalchemy import select
    from app.infrastructure.db.models import ProjectCheckout as PC

    async with factory() as session:
        rows = (
            await session.execute(select(PC).where(PC.project_id == project_id))
        ).scalars().all()
        assert len(rows) == 1  # upsert, not duplicate
        assert rows[0].checkout_path == "/x/moved"
        assert rows[0].user_id == user.id


@pytest.mark.asyncio
async def test_save_checkout_requires_user_token_and_visible_project(client) -> None:
    import hashlib

    from app.infrastructure.db.connection import get_sessionmaker
    from app.infrastructure.db.models import Project, User

    token = "mcp-hidden-project-token"
    factory = get_sessionmaker()
    async with factory() as session:
        user = User(
            email="hidden@example.com",
            role="user",
            mcp_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        project = Project(
            tag="hidden-project",
            github_repo="org/hidden",
            github_repo_key="org/hidden",
            hidden=True,
        )
        session.add_all([user, project])
        await session.commit()
        project_id = project.id

    class NoAuthCtx:
        class request_context:  # noqa: N801
            class request:  # noqa: N801
                headers: dict[str, str] = {}

    class AuthCtx:
        class request_context:  # noqa: N801
            class request:  # noqa: N801
                headers = {"authorization": f"Bearer {token}"}

    app = create_app()
    server = app.state.mcp_server
    function = server._tool_manager._tools["save_checkout_mapping"].fn  # type: ignore[attr-defined]
    unauthenticated = await function(project_id, "/x", ctx=NoAuthCtx())
    hidden = await function(project_id, "/x", ctx=AuthCtx())
    assert unauthenticated == {"error": "authentication_required"}
    assert hidden == {"error": "not_found", "project_id": project_id}
