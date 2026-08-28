"""Focused contracts for the repository-identity atomic capability."""

from __future__ import annotations

import pytest

from app.modules.atomic.provenance.repository_identity import (
    InvalidRepositoryIdentityError,
    merge_github_aliases,
    parse_github_repository,
)


def _row(path: str, runs: int = 1, last: str | None = None, cat: bool = False):
    return {
        "project_path": path,
        "run_count": runs,
        "last_scan_at": last,
        "has_catalogue": cat,
    }


def test_parse_github_repository_keeps_supported_forms() -> None:
    assert parse_github_repository("26457513/assurance-scan") == "26457513/assurance-scan"
    assert (
        parse_github_repository("https://github.com/26457513/assurance-scan.git/")
        == "26457513/assurance-scan"
    )
    assert parse_github_repository("") is None


@pytest.mark.parametrize(
    "value",
    ["https://gitlab.com/acme/project", "project", "acme/project/extra"],
)
def test_parse_github_repository_rejects_unsupported_forms(value: str) -> None:
    with pytest.raises(InvalidRepositoryIdentityError):
        parse_github_repository(value)


def test_merge_preserves_rows_and_combines_existing_statistics() -> None:
    local = _row("/workspace/assurance-scan", 2, "2026-08-18T09:00:00")
    local["custom"] = "preserved"
    github = _row(
        "github:26457513/assurance-scan", 3, "2026-08-18T12:00:00", True
    )

    merged = merge_github_aliases([local, github], "26457513")

    assert merged == [
        {
            **local,
            "github_project": "github:26457513/assurance-scan",
            "run_count": 5,
            "last_scan_at": "2026-08-18T12:00:00",
            "has_catalogue": True,
        }
    ]


def test_merge_without_org_returns_the_original_list() -> None:
    projects = [_row("/workspace/assurance-scan")]
    assert merge_github_aliases(projects, "") is projects
