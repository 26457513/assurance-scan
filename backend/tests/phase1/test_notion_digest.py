"""Digest rendering: table + chart blocks, correct counts, sane bars."""
from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def seeded():
    from app.infrastructure.db.connection import get_engine, get_sessionmaker
    from app.infrastructure.db.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.infrastructure.db.models import Finding, Project, Run

    factory = get_sessionmaker()
    async with factory() as session:
        session.add(Project(tag="p1", local_path="github:org/p1", github_repo="org/p1"))
        session.add(Run(run_id="nd-1", project_path="github:org/p1", status="completed",
                        git_branch="main", started_at=dt.datetime.now(dt.timezone.utc)))
        await session.commit()
        session.add_all([
            Finding(run_id="nd-1", severity="CRITICAL", scanner_kind="semgrep", message="c"),
            Finding(run_id="nd-1", severity="HIGH", scanner_kind="semgrep", message="h"),
            Finding(run_id="nd-1", severity="HIGH", scanner_kind="gitleaks", message="h2"),
            Finding(run_id="nd-1", severity="LOW", scanner_kind="trivy", message="l"),
        ])
        await session.commit()
    yield
    from app.infrastructure.db import connection as _conn
    _conn._engine = None
    _conn._sessionmaker = None


@pytest.mark.asyncio
async def test_digest_blocks(seeded) -> None:
    from app.notion_digest import build_digest

    blocks, summary = await build_digest()
    assert summary == {"projects": 1, "critical": 1, "high": 2, "failed_runs": 0}

    table = next(b for b in blocks if b["type"] == "table")
    assert table["table"]["table_width"] == 9
    assert table["table"]["has_column_header"] is True
    body = table["table"]["children"][1]["table_row"]["cells"]
    cell_vals = [c[0]["text"]["content"] for c in body]
    assert cell_vals[0] == "p1" and cell_vals[1] == "main"
    assert "(completed)" in cell_vals[2]
    assert cell_vals[3:8] == ["1", "2", "0", "1", "—"]
    assert cell_vals[8] == "—"

    assert not any(b["type"] == "code" for b in blocks)  # chart removed
    headings = [b["heading_2"]["rich_text"][0]["text"]["content"]
                for b in blocks if b["type"] == "heading_2"]
    assert headings == ["Open PRs"]
    [b["bulleted_list_item"]["rich_text"][0]["text"]["content"]
                    for b in blocks if b["type"] == "bulleted_list_item"]
    # no GitHub token for the test org -> classified unavailable PR row
    pr_table = next(b for b in blocks if b["type"] == "table"
                    and b["table"]["children"][0]["table_row"]["cells"][0][0]["text"]["content"] == "PR")
    assert any("p1 — GitHub unavailable" in r["table_row"]["cells"][0][0]["text"]["content"]
               for r in pr_table["table"]["children"][1:])
