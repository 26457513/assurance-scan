"""Tests for the project registry endpoints."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select as sa_select

from server.api.routes.projects import _parse_github_repo, list_projects
from server.db.models import Project, Run


class _FakeRequest:
    def __init__(self, org: str) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(settings=SimpleNamespace(github_org=org))
        )


def test_parse_github_repo_forms() -> None:
    assert _parse_github_repo("https://github.com/26457513/doc2context") == "26457513/doc2context"
    assert _parse_github_repo("https://github.com/26457513/doc2context.git") == "26457513/doc2context"
    assert _parse_github_repo("https://github.com/26457513/doc2context/") == "26457513/doc2context"
    assert _parse_github_repo("26457513/doc2context") == "26457513/doc2context"
    assert _parse_github_repo("") is None
    for bad in ("https://gitlab.com/x/y", "not a url", "a/b/c"):
        try:
            _parse_github_repo(bad)
            raise AssertionError(f"expected 422 for {bad}")
        except HTTPException as exc:
            assert exc.status_code == 422


async def test_registered_project_unifies_identities(session) -> None:
    session.add(Project(tag="doc2context", local_path="/Users/jd/Development/doc2context",
                        github_repo="26457513/doc2context"))
    session.add(Run(run_id="local-1", project_path="/Users/jd/Development/doc2context", status="completed"))
    session.add(Run(run_id="gh-1", project_path="github:26457513/doc2context", status="completed"))
    await session.commit()

    res = await list_projects(_FakeRequest("26457513"), session=session)
    registered = [p for p in res["projects"] if p.get("registered")]
    assert len(registered) == 1
    row = registered[0]
    assert row["tag"] == "doc2context"
    assert row["project_path"] == "/Users/jd/Development/doc2context"
    assert row["github_project"] == "github:26457513/doc2context"
    assert row["run_count"] == 2
    # No derived leftover rows for the consumed identities.
    assert all(p["project_path"] != "github:26457513/doc2context" for p in res["projects"])


async def test_update_project_changes_fields(session) -> None:
    from server.api.routes.projects import ProjectUpdate, update_project

    session.add(Project(tag="old-tag", local_path="/tmp", github_repo=None))
    await session.commit()
    row_id = (await session.execute(sa_select(Project))).scalars().one().id

    res = await update_project(row_id, ProjectUpdate(tag="new-tag", github_url="26457513/x"), session=session)
    assert res["status"] == "updated"
    assert res["tag"] == "new-tag"
    assert res["github_repo"] == "26457513/x"


async def test_update_project_validates_path(session) -> None:
    from fastapi import HTTPException

    from server.api.routes.projects import ProjectUpdate, update_project

    session.add(Project(tag="p", local_path="/tmp"))
    await session.commit()
    row_id = (await session.execute(sa_select(Project))).scalars().one().id

    try:
        await update_project(row_id, ProjectUpdate(local_path="/definitely/not/a/dir"), session=session)
        raise AssertionError("expected 422")
    except HTTPException as exc:
        assert exc.status_code == 422

    try:
        await update_project(999999, ProjectUpdate(tag="x"), session=session)
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404


async def test_delete_project_tombstones_registry_row(session) -> None:
    from fastapi import HTTPException

    from server.api.routes.projects import delete_project

    session.add(Project(tag="temp", local_path="/tmp"))
    await session.commit()
    row_id = (await session.execute(sa_select(Project))).scalars().one().id

    res = await delete_project(row_id, session=session)
    assert res["status"] == "deleted"
    # Tombstoned, not dropped — the row survives hidden.
    row = (await session.execute(sa_select(Project))).scalars().one()
    assert row.hidden is True

    try:
        await delete_project(row_id, session=session)
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404
