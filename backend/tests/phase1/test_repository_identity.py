"""Focused contracts for the repository-identity atomic capability."""

from __future__ import annotations

import pytest

from app.modules.atomic.provenance.repository_identity import (
    InvalidRepositoryIdentityError,
    normalize_github_repository_key,
    parse_github_repository,
)


def test_parse_github_repository_keeps_supported_forms() -> None:
    assert parse_github_repository("26457513/assurance-scan") == "26457513/assurance-scan"
    assert (
        parse_github_repository("https://github.com/26457513/assurance-scan.git/")
        == "26457513/assurance-scan"
    )
    assert parse_github_repository("") is None
    assert (
        parse_github_repository("git@github.com:26457513/assurance-scan.git")
        == "26457513/assurance-scan"
    )
    assert (
        parse_github_repository("ssh://git@github.com/26457513/assurance-scan.git")
        == "26457513/assurance-scan"
    )
    assert normalize_github_repository_key("OpenAI/Assurance-Scan") == (
        "openai/assurance-scan"
    )


@pytest.mark.parametrize(
    "value",
    [
        "https://gitlab.com/acme/project",
        "project",
        "acme/project/extra",
        "https://github.com/acme/project?tab=readme",
        "https://github.com/acme/project#main",
        "https://github.com.evil.test/acme/project",
        "https://user@github.com/acme/project",
        "ssh://root@github.com/acme/project",
        "git@github.com:acme/project/extra",
    ],
)
def test_parse_github_repository_rejects_unsupported_forms(value: str) -> None:
    with pytest.raises(InvalidRepositoryIdentityError):
        parse_github_repository(value)
