from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Sequence

import pytest

from app.modules.atomic.local_cli.git_metadata import (
    GitCommandResult,
    GitMetadataError,
    SubprocessGitCommand,
    collect_git_metadata,
    normalize_github_repository,
)


class FakeGit:
    def __init__(self, root: Path, *, detached: bool = False, dirty: bool = False) -> None:
        self.root = root
        self.detached = detached
        self.dirty = dirty

    def run(self, arguments: Sequence[str], *, cwd: Path) -> GitCommandResult:
        values = {
            ("rev-parse", "--show-toplevel"): str(self.root).encode(),
            ("config", "--get", "remote.origin.url"): b"git@github.com:26457513/assurance-scan.git\n",
            ("rev-parse", "--show-object-format"): b"sha1\n",
            ("rev-parse", "HEAD"): b"a" * 40,
            ("status", "--porcelain=v1", "-z"): b" M app.py\0" if self.dirty else b"",
        }
        if tuple(arguments) == ("symbolic-ref", "--quiet", "--short", "HEAD"):
            return GitCommandResult(1, b"") if self.detached else GitCommandResult(0, b"feature/local\n")
        return GitCommandResult(0, values[tuple(arguments)])


@pytest.mark.parametrize(
    "remote",
    [
        "git@github.com:26457513/assurance-scan.git",
        "https://github.com/26457513/assurance-scan.git",
        "ssh://git@github.com/26457513/assurance-scan.git",
        "26457513/assurance-scan",
    ],
)
def test_remote_forms_normalize_to_one_repository(remote: str) -> None:
    assert normalize_github_repository(remote) == "26457513/assurance-scan"


@pytest.mark.parametrize(
    "remote",
    ["https://gitlab.com/a/b", "https://user@github.com/a/b", "git@github.com:a/b/c", "../a/b"],
)
def test_remote_normalization_rejects_unsafe_or_non_github_values(remote: str) -> None:
    with pytest.raises(GitMetadataError):
        normalize_github_repository(remote)


def test_collect_supports_detached_head_dirty_state_and_override(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    metadata = collect_git_metadata(root, FakeGit(root, detached=True, dirty=True), project_override="Owner/Upstream")
    assert metadata.repository == "Owner/Upstream"
    assert metadata.project_override == "Owner/Upstream"
    assert metadata.branch is None
    assert metadata.working_tree_dirty is True
    assert metadata.commit == "a" * 40


def test_collect_requires_invocation_from_repository_root(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    with pytest.raises(GitMetadataError, match="repository root"):
        collect_git_metadata(child, FakeGit(tmp_path.resolve()))


def test_bounded_subprocess_adapter_collects_real_checkout_metadata(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "remote", "add", "origin", "https://github.com/Owner/Repo.git"],
        check=True,
    )
    (tmp_path / "tracked.txt").write_text("content")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "initial"], check=True)
    metadata = collect_git_metadata(tmp_path, SubprocessGitCommand())
    assert metadata.repository == "Owner/Repo"
    assert metadata.git_object_format == "sha1"
    assert metadata.working_tree_dirty is False
