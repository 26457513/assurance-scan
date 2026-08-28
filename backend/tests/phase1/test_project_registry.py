"""Tests for the durable project registry endpoints."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes.projects import (
    ProjectUpdate,
    _parse_github_repo,
    delete_project,
    list_projects,
    update_project,
)
from app.infrastructure.db.models import Project, Run


def test_parse_github_repo_forms_are_strict_and_source_neutral() -> None:
    expected = "26457513/doc2context"
    assert _parse_github_repo("https://github.com/26457513/doc2context") == expected
    assert _parse_github_repo("git@github.com:26457513/doc2context.git") == expected
    assert _parse_github_repo("ssh://git@github.com/26457513/doc2context") == expected
    assert _parse_github_repo(expected) == expected
    assert _parse_github_repo("") is None
    for bad in (
        "https://gitlab.com/x/y",
        "not a url",
        "a/b/c",
        "https://github.com/x/y?tab=readme",
    ):
        try:
            _parse_github_repo(bad)
            raise AssertionError(f"expected 422 for {bad}")
        except HTTPException as exc:
            assert exc.status_code == 422


async def test_registered_project_aggregates_all_origins_by_id(session) -> None:
    project = Project(
        tag="doc2context",
        local_path="/workspace/doc2context",
        github_repo="26457513/doc2context",
        github_repo_key="26457513/doc2context",
    )
    session.add(project)
    await session.flush()
    session.add_all(
        [
            Run(
                run_id="server-1",
                project_id=project.id,
                origin="server",
                status="completed",
            ),
            Run(
                run_id="gh-1",
                project_id=project.id,
                origin="github-actions",
                working_tree_dirty=False,
                commit_sha="0" * 40,
                git_object_format="sha1",
                github_run_id=1,
                status="completed",
            ),
        ]
    )
    await session.commit()

    response = await list_projects(session=session)
    assert response["projects"] == [
        {
            "id": project.id,
            "tag": "doc2context",
            "local_path": "/workspace/doc2context",
            "github_repo": "26457513/doc2context",
            "github_repository_id": None,
            "default_scan_ref": None,
            "run_count": 2,
            "last_scan_at": response["projects"][0]["last_scan_at"],
            "has_catalogue": False,
        }
    ]


async def test_update_project_changes_fields_and_can_clear_locator(session) -> None:
    project = Project(tag="old-tag", local_path="/tmp")
    session.add(project)
    await session.commit()

    response = await update_project(
        project.id,
        ProjectUpdate(
            tag="new-tag",
            local_path=None,
            github_repo="OpenAI/Example",
        ),
        session=session,
    )
    assert response["status"] == "updated"
    assert response["tag"] == "new-tag"
    assert response["local_path"] is None
    assert response["github_repo"] == "OpenAI/Example"
    assert project.github_repo_key == "openai/example"


async def test_update_project_rejects_missing_locator(session) -> None:
    project = Project(tag="project", local_path="/tmp")
    session.add(project)
    await session.commit()

    try:
        await update_project(
            project.id,
            ProjectUpdate(local_path=None),
            session=session,
        )
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400


async def test_delete_project_tombstones_and_deletes_runs_by_id(session) -> None:
    project = Project(tag="temp", local_path="/tmp")
    session.add(project)
    await session.flush()
    session.add(
        Run(run_id="server-1", project_id=project.id, origin="server", status="completed")
    )
    await session.commit()

    response = await delete_project(project.id, session=session)
    assert response["status"] == "deleted"
    assert project.hidden is True
    assert (await session.execute(select(Run))).scalars().all() == []

    try:
        await delete_project(project.id, session=session)
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404
