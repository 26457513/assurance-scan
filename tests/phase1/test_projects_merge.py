"""Tests for path-derived github alias merging in the projects registry."""
from __future__ import annotations

from server.api.routes.projects import merge_github_aliases


def _row(path, runs=1, last="2026-08-18T10:00:00", cat=False):
    return {"project_path": path, "run_count": runs, "last_scan_at": last, "has_catalogue": cat}


def test_github_project_folds_into_matching_local_folder() -> None:
    projects = [
        _row("/Users/jd/Development/doc2context", runs=2, last="2026-08-18T09:00:00"),
        _row("github:26457513/doc2context", runs=7, last="2026-08-18T12:00:00", cat=True),
    ]
    merged = merge_github_aliases(projects, "26457513")
    assert len(merged) == 1
    row = merged[0]
    assert row["project_path"] == "/Users/jd/Development/doc2context"
    assert row["github_project"] == "github:26457513/doc2context"
    assert row["run_count"] == 9
    assert row["last_scan_at"] == "2026-08-18T12:00:00"
    assert row["has_catalogue"] is True


def test_unmatched_projects_stay_separate() -> None:
    projects = [
        _row("/Users/jd/Development/solo-project"),
        _row("github:26457513/assurance-scan"),  # no local match
    ]
    merged = merge_github_aliases(projects, "26457513")
    assert len(merged) == 2
    assert {p["project_path"] for p in merged} == {
        "/Users/jd/Development/solo-project",
        "github:26457513/assurance-scan",
    }


def test_no_org_means_no_merge() -> None:
    projects = [_row("/x/doc2context"), _row("github:26457513/doc2context")]
    assert len(merge_github_aliases(projects, "")) == 2
