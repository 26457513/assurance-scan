"""Git-backed tracked and non-ignored source index adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

from app.modules.atomic.local_cli.git_metadata import GitCommandPort

from .models import SourceSnapshotError


_SUBMODULE = re.compile(r"^(?P<state>[ +U-])(?P<sha>[0-9a-f]{40,64}) (?P<path>.+?)(?: \(.+\))?$")


class GitSnapshotIndex:
    """Use Git's index/ignore rules and recursively expand initialized submodules."""

    def __init__(self, git: GitCommandPort) -> None:
        self.git = git

    def included_paths(self, root: Path) -> list[str]:
        paths = set(self._listed(root))
        for submodule in self._initialized_submodules(root):
            submodule_root = root / submodule
            paths.add(submodule)
            paths.update(f"{submodule}/{path}" for path in self._listed(submodule_root))
        return sorted(paths)

    def fingerprint(self, root: Path) -> str:
        digest = hashlib.sha256()
        head = self.git.run(("rev-parse", "HEAD"), cwd=root)
        if head.returncode != 0:
            raise SourceSnapshotError("unable to fingerprint Git HEAD")
        digest.update(head.stdout.strip() + b"\x00")
        for relative in self.included_paths(root):
            path = _safe_path(root, relative)
            try:
                info = path.lstat()
            except FileNotFoundError:
                digest.update(relative.encode("utf-8") + b"\0missing\n")
                continue
            document = {
                "path": relative,
                "mode": stat.S_IFMT(info.st_mode) | stat.S_IMODE(info.st_mode),
                "size": info.st_size,
                "mtime_ns": info.st_mtime_ns,
                "ctime_ns": info.st_ctime_ns,
                "inode": info.st_ino,
                "target": os.readlink(path) if stat.S_ISLNK(info.st_mode) else None,
            }
            digest.update(json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
        return digest.hexdigest()

    def lfs_paths(self, root: Path) -> list[str]:
        paths = set(self._lfs_paths(root, self._listed(root)))
        for submodule in self._initialized_submodules(root):
            submodule_root = root / submodule
            paths.update(
                f"{submodule}/{path}"
                for path in self._lfs_paths(submodule_root, self._listed(submodule_root))
            )
        return sorted(paths)

    def _lfs_paths(self, root: Path, paths: list[str]) -> list[str]:
        lfs_paths: list[str] = []
        for offset in range(0, len(paths), 256):
            batch = paths[offset : offset + 256]
            result = self.git.run(("check-attr", "-z", "filter", "--", *batch), cwd=root)
            if result.returncode != 0:
                raise SourceSnapshotError("unable to inspect Git LFS attributes")
            fields = result.stdout.split(b"\x00")
            if fields and fields[-1] == b"":
                fields.pop()
            if len(fields) % 3:
                raise SourceSnapshotError("Git returned malformed attribute metadata")
            for index in range(0, len(fields), 3):
                try:
                    path = fields[index].decode("utf-8")
                    attribute = fields[index + 1].decode("ascii")
                    value = fields[index + 2].decode("ascii")
                except UnicodeDecodeError as exc:
                    raise SourceSnapshotError("Git attribute metadata is invalid") from exc
                if attribute != "filter":
                    raise SourceSnapshotError("Git returned unexpected attribute metadata")
                if value == "lfs":
                    lfs_paths.append(path)
        return lfs_paths

    def _listed(self, root: Path) -> list[str]:
        result = self.git.run(("ls-files", "--cached", "--others", "--exclude-standard", "-z"), cwd=root)
        if result.returncode != 0:
            raise SourceSnapshotError("unable to list tracked and non-ignored files")
        return _nul_paths(result.stdout)

    def _initialized_submodules(self, root: Path) -> list[str]:
        result = self.git.run(("submodule", "status", "--recursive"), cwd=root)
        if result.returncode != 0:
            raise SourceSnapshotError("unable to inspect Git submodules")
        initialized: list[str] = []
        for raw_line in result.stdout.decode("utf-8").splitlines():
            match = _SUBMODULE.fullmatch(raw_line)
            if match is None:
                raise SourceSnapshotError("Git returned malformed submodule metadata")
            if match.group("state") != "-":
                initialized.append(match.group("path"))
        return initialized


def _nul_paths(payload: bytes) -> list[str]:
    result: list[str] = []
    for value in payload.split(b"\x00"):
        if not value:
            continue
        try:
            result.append(value.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise SourceSnapshotError("Git path is not valid UTF-8") from exc
    return result


def _safe_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts) or "\\" in relative:
        raise SourceSnapshotError("Git returned a path outside the repository")
    return root / pure


__all__ = ["GitSnapshotIndex"]
