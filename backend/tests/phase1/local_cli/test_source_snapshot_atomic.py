from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.modules.atomic.local_cli.source_snapshot import (
    GitSnapshotIndex,
    SnapshotIndexPort,
    SnapshotLimits,
    SourceChangedError,
    SourceSnapshotError,
    canonical_snapshot_hash,
    create_source_snapshot,
)
from app.modules.atomic.local_cli.git_metadata import GitCommandResult, SubprocessGitCommand


class FakeIndex(SnapshotIndexPort):
    def __init__(self, paths: list[str], *, lfs: list[str] | None = None, fingerprints: list[str] | None = None) -> None:
        self.paths = paths
        self.lfs = lfs or []
        self.fingerprints = fingerprints or ["stable", "stable"]

    def included_paths(self, root: Path) -> list[str]:
        return self.paths

    def fingerprint(self, root: Path) -> str:
        return self.fingerprints.pop(0)

    def lfs_paths(self, root: Path) -> list[str]:
        return self.lfs


LIMITS = SnapshotLimits(max_entries=100, max_file_bytes=1024, max_total_bytes=4096, free_space_reserve_bytes=0)


def test_snapshot_includes_listed_files_symlink_without_following_and_stable_hash(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "tracked.txt").write_text("tracked")
    (source / "untracked.txt").write_text("untracked")
    (source / "link").symlink_to("../../outside-secret")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("secret")
    paths = ["untracked.txt", ".git/config", "link", "tracked.txt"]

    first = create_source_snapshot(source, tmp_path / "snapshot-1", FakeIndex(paths), limits=LIMITS)
    second = create_source_snapshot(source, tmp_path / "snapshot-2", FakeIndex(reversed(paths)), limits=LIMITS)
    assert first.source_content_hash == second.source_content_hash
    assert canonical_snapshot_hash(first.entries) == first.source_content_hash
    assert (first.root / "link").is_symlink()
    assert os.readlink(first.root / "link") == "../../outside-secret"
    assert not (first.root / ".git").exists()
    assert (first.root.stat().st_uid, first.root.stat().st_gid) == (os.getuid(), os.getgid())
    assert {entry.path for entry in first.entries} == {"tracked.txt", "untracked.txt", "link"}


def test_snapshot_records_lfs_state_and_submodule_warning(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "pointer.bin").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 1\n"
    )
    (source / "hydrated.bin").write_bytes(b"binary")
    (source / "missing-submodule").mkdir()
    result = create_source_snapshot(
        source,
        tmp_path / "snapshot",
        FakeIndex(
            ["pointer.bin", "hydrated.bin", "missing-submodule"],
            lfs=["pointer.bin", "hydrated.bin"],
        ),
        limits=LIMITS,
    )
    assert result.lfs_state == "mixed"
    assert result.warnings == ("unexpanded_submodule:missing-submodule",)


def test_snapshot_rejects_traversal_duplicates_size_and_cleans_partial(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "large").write_bytes(b"x" * 20)
    with pytest.raises(SourceSnapshotError, match="relative"):
        create_source_snapshot(source, tmp_path / "bad-path", FakeIndex(["../large"]), limits=LIMITS)
    with pytest.raises(SourceSnapshotError, match="duplicate"):
        create_source_snapshot(source, tmp_path / "duplicate", FakeIndex(["large", "large"]), limits=LIMITS)
    with pytest.raises(SourceSnapshotError, match="file size"):
        create_source_snapshot(
            source,
            tmp_path / "oversize",
            FakeIndex(["large"]),
            limits=SnapshotLimits(max_file_bytes=10, max_total_bytes=100, free_space_reserve_bytes=0),
        )
    assert not (tmp_path / "oversize").exists()


def test_snapshot_never_follows_symlinked_parent_outside_repository(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("do not copy")
    (source / "linked-directory").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SourceSnapshotError, match="unsafe parent"):
        create_source_snapshot(
            source,
            tmp_path / "snapshot",
            FakeIndex(["linked-directory/secret"]),
            limits=LIMITS,
        )
    assert not (tmp_path / "snapshot").exists()


def test_snapshot_detects_repository_mutation_and_removes_output(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "file").write_text("content")
    destination = tmp_path / "snapshot"
    with pytest.raises(SourceChangedError):
        create_source_snapshot(source, destination, FakeIndex(["file"], fingerprints=["before", "after"]), limits=LIMITS)
    assert not destination.exists()


class SnapshotGit:
    def __init__(self, root: Path) -> None:
        self.root = root

    def run(self, arguments, *, cwd: Path) -> GitCommandResult:
        command = tuple(arguments)
        if command == ("ls-files", "--cached", "--others", "--exclude-standard", "-z"):
            payload = b"root.txt\0module\0" if cwd == self.root else b"nested.txt\0"
            return GitCommandResult(0, payload)
        if command == ("submodule", "status", "--recursive"):
            if cwd != self.root:
                return GitCommandResult(0, b"")
            return GitCommandResult(0, b" aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa module (heads/main)\n")
        if command[:4] == ("check-attr", "-z", "filter", "--"):
            fields = []
            for path in command[4:]:
                value = "lfs" if path == "root.txt" else "unspecified"
                fields.extend((path, "filter", value))
            return GitCommandResult(0, ("\0".join(fields) + "\0").encode())
        if command == ("rev-parse", "HEAD"):
            return GitCommandResult(0, b"a" * 40)
        raise AssertionError(command)


def test_git_snapshot_index_expands_submodules_and_detects_lfs_without_git_lfs(tmp_path: Path) -> None:
    (tmp_path / "root.txt").write_text("root")
    (tmp_path / "module").mkdir()
    (tmp_path / "module" / "nested.txt").write_text("nested")
    index = GitSnapshotIndex(SnapshotGit(tmp_path))
    assert index.included_paths(tmp_path) == ["module", "module/nested.txt", "root.txt"]
    assert index.lfs_paths(tmp_path) == ["root.txt"]
    assert len(index.fingerprint(tmp_path)) == 64


def test_git_native_lfs_attribute_detection_needs_no_git_lfs_binary(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitattributes").write_text("*.bin filter=lfs\n")
    (tmp_path / "asset.bin").write_bytes(b"hydrated")
    (tmp_path / "ordinary.txt").write_text("ordinary")
    index = GitSnapshotIndex(SubprocessGitCommand())
    assert index.lfs_paths(tmp_path) == ["asset.bin"]
