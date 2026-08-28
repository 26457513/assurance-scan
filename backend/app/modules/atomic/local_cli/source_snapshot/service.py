"""Bounded, symlink-safe snapshot copying and canonical content hashing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import unicodedata
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from .models import (
    SOURCE_MANIFEST_VERSION,
    SnapshotEntry,
    SnapshotIndexPort,
    SnapshotLimits,
    SourceChangedError,
    SourceSnapshot,
    SourceSnapshotError,
)


_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"


def create_source_snapshot(
    source_root: Path,
    destination: Path,
    index: SnapshotIndexPort,
    *,
    excluded_roots: tuple[Path, ...] = (),
    limits: SnapshotLimits = SnapshotLimits(),
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> SourceSnapshot:
    """Copy one stable Git view, deleting all partial output on failure."""
    source = source_root.resolve(strict=True)
    uid = os.getuid() if owner_uid is None else owner_uid
    gid = os.getgid() if owner_gid is None else owner_gid
    _validate_requested_owner(uid)
    if destination.exists() or destination.is_symlink():
        raise SourceSnapshotError("snapshot destination already exists")
    _ensure_owner_directory(destination.parent, uid, gid)
    before = index.fingerprint(source)
    raw_paths = list(index.included_paths(source))
    if len(raw_paths) > limits.max_entries:
        raise SourceSnapshotError("snapshot entry limit exceeded")
    paths = _normalize_paths(raw_paths, source, excluded_roots)
    lfs_paths = set(_normalize_paths(index.lfs_paths(source), source, excluded_roots))
    estimates, estimated_total = _estimate(source, paths, limits)
    free = shutil.disk_usage(destination.parent).free
    if free < estimated_total + limits.free_space_reserve_bytes:
        raise SourceSnapshotError("insufficient free space for source snapshot")

    entries: list[SnapshotEntry] = []
    warnings: list[str] = []
    lfs_pointer = False
    lfs_hydrated = False
    total = 0
    destination.mkdir(mode=0o700)
    os.chown(destination, uid, gid)
    os.chmod(destination, 0o700)
    try:
        for relative in paths:
            source_path = _safe_source_path(source, relative)
            destination_path = destination / relative
            before_info = source_path.lstat()
            if stat.S_ISDIR(before_info.st_mode):
                if not any(path.startswith(f"{relative}/") for path in paths):
                    warnings.append(f"unexpanded_submodule:{relative}")
                continue
            _ensure_snapshot_directory(destination, destination_path.parent, uid, gid)
            if stat.S_ISLNK(before_info.st_mode):
                target = os.readlink(source_path)
                if "\x00" in target:
                    raise SourceSnapshotError("symlink target contains NUL")
                os.symlink(target, destination_path)
                os.lchown(destination_path, uid, gid)
                encoded_target = os.fsencode(target)
                total += len(encoded_target)
                if _identity(source_path.lstat()) != _identity(before_info):
                    raise SourceChangedError("symlink changed during snapshot creation")
                entries.append(
                    SnapshotEntry(
                        path=relative,
                        kind="symlink",
                        mode=stat.S_IMODE(before_info.st_mode),
                        size=len(encoded_target),
                        symlink_target=target,
                    )
                )
            elif stat.S_ISREG(before_info.st_mode):
                if before_info.st_nlink != 1:
                    raise SourceSnapshotError("hard-linked source file is not supported")
                size, content_hash, is_lfs_pointer = _copy_regular_file(
                    source_path,
                    destination_path,
                    before_info,
                    limits,
                    uid,
                    gid,
                )
                total += size
                if total > limits.max_total_bytes:
                    raise SourceSnapshotError("snapshot total size limit exceeded")
                if relative in lfs_paths:
                    lfs_pointer |= is_lfs_pointer
                    lfs_hydrated |= not is_lfs_pointer
                entries.append(
                    SnapshotEntry(
                        path=relative,
                        kind="file",
                        mode=stat.S_IMODE(before_info.st_mode),
                        size=size,
                        content_hash=content_hash,
                    )
                )
            else:
                raise SourceSnapshotError("special files are not supported in snapshots")
            if total > limits.max_total_bytes:
                raise SourceSnapshotError("snapshot total size limit exceeded")
            if estimates[relative] != before_info.st_size:
                raise SourceChangedError("source changed while snapshot was created")
        if index.fingerprint(source) != before:
            raise SourceChangedError("source changed while snapshot was created")
        ordered = tuple(sorted(entries, key=lambda entry: entry.path))
        return SourceSnapshot(
            root=destination,
            entries=ordered,
            source_content_hash=canonical_snapshot_hash(ordered),
            source_manifest_version=SOURCE_MANIFEST_VERSION,
            total_bytes=total,
            lfs_state=_lfs_state(bool(lfs_paths), lfs_pointer, lfs_hydrated),
            warnings=tuple(warnings),
        )
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def canonical_snapshot_hash(entries: tuple[SnapshotEntry, ...]) -> str:
    """Hash the locked path-sorted v1 entry representation."""
    digest = hashlib.sha256()
    digest.update(SOURCE_MANIFEST_VERSION.encode("ascii") + b"\x00")
    for entry in sorted(entries, key=lambda item: item.path):
        document = {
            "content_hash": entry.content_hash,
            "kind": entry.kind,
            "mode": f"{entry.mode:04o}",
            "path": entry.path,
            "size": entry.size,
            "symlink_target": entry.symlink_target,
        }
        digest.update(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _normalize_paths(paths: Iterable[str], source: Path, excluded_roots: tuple[Path, ...]) -> list[str]:
    excluded = {".git", ".assurance-scan"}
    for root in excluded_roots:
        try:
            excluded.add(root.resolve().relative_to(source).as_posix())
        except ValueError:
            continue
    result: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if (
            not isinstance(raw, str)
            or not raw
            or "\x00" in raw
            or "\\" in raw
            or re.match(r"^[A-Za-z]:", raw)
        ):
            raise SourceSnapshotError("snapshot path is invalid")
        pure = PurePosixPath(raw)
        if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
            raise SourceSnapshotError("snapshot path is not repository-relative")
        normalized = unicodedata.normalize("NFC", pure.as_posix())
        if normalized in seen:
            raise SourceSnapshotError("duplicate normalized snapshot path")
        seen.add(normalized)
        if any(normalized == item or normalized.startswith(f"{item}/") for item in excluded):
            continue
        result.append(normalized)
    return sorted(result)


def _estimate(source: Path, paths: list[str], limits: SnapshotLimits) -> tuple[dict[str, int], int]:
    estimates: dict[str, int] = {}
    total = 0
    for relative in paths:
        try:
            source_path = _safe_source_path(source, relative)
            info = source_path.lstat()
        except FileNotFoundError as exc:
            raise SourceChangedError("source changed before snapshot creation") from exc
        if stat.S_ISREG(info.st_mode):
            if info.st_size > limits.max_file_bytes:
                raise SourceSnapshotError("snapshot file size limit exceeded")
            size = info.st_size
        elif stat.S_ISLNK(info.st_mode):
            size = len(os.fsencode(os.readlink(source_path)))
        elif stat.S_ISDIR(info.st_mode):
            # A listed directory is a gitlink/submodule marker. It is not
            # copied into the payload, and directory st_size is filesystem-
            # dependent (commonly 4096 on Linux), so it must not consume the
            # byte quota or free-space estimate.
            size = 0
        else:
            raise SourceSnapshotError("special files are not supported in snapshots")
        estimates[relative] = info.st_size
        total += size
        if total > limits.max_total_bytes:
            raise SourceSnapshotError("snapshot total size limit exceeded")
    return estimates, total


def _copy_regular_file(
    source: Path,
    destination: Path,
    before: os.stat_result,
    limits: SnapshotLimits,
    owner_uid: int,
    owner_gid: int,
) -> tuple[int, str, bool]:
    digest = hashlib.sha256()
    size = 0
    prefix = bytearray()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    source_fd = os.open(source, flags)
    try:
        opened = os.fstat(source_fd)
        if _identity(opened) != _identity(before):
            raise SourceChangedError("source changed before file copy")
        destination_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IMODE(before.st_mode))
        try:
            os.fchown(destination_fd, owner_uid, owner_gid)
            os.fchmod(destination_fd, stat.S_IMODE(before.st_mode))
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limits.max_file_bytes:
                    raise SourceSnapshotError("snapshot file size limit exceeded")
                if len(prefix) < len(_LFS_PREFIX):
                    prefix.extend(chunk[: len(_LFS_PREFIX) - len(prefix)])
                digest.update(chunk)
                _write_all(destination_fd, chunk)
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
        after = os.fstat(source_fd)
        if _identity(after) != _identity(before) or size != before.st_size:
            raise SourceChangedError("source changed during file copy")
    finally:
        os.close(source_fd)
    return size, digest.hexdigest(), bytes(prefix).startswith(_LFS_PREFIX)


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        stat.S_IMODE(info.st_mode),
        info.st_nlink,
    )


def _safe_source_path(root: Path, relative: str) -> Path:
    candidate = root
    parts = PurePosixPath(relative).parts
    for part in parts[:-1]:
        candidate = candidate / part
        info = candidate.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise SourceSnapshotError("snapshot path has an unsafe parent component")
    return candidate / parts[-1]


def _ensure_owner_directory(path: Path, uid: int, gid: int) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        if current.is_symlink():
            raise SourceSnapshotError("snapshot parent must not contain symlinks")
        missing.append(current)
        current = current.parent
    _validate_owner_directory(current, uid, gid)
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        os.chown(directory, uid, gid)
        os.chmod(directory, 0o700)
    _validate_owner_directory(path, uid, gid)


def _validate_owner_directory(path: Path, uid: int, gid: int) -> None:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != uid
        or info.st_gid != gid
        or info.st_mode & 0o077
    ):
        raise SourceSnapshotError("snapshot parent must be an owner-only directory")


def _ensure_snapshot_directory(root: Path, path: Path, uid: int, gid: int) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if not current.exists():
            current.mkdir(mode=0o700)
            os.chown(current, uid, gid)
            os.chmod(current, 0o700)
        info = current.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != uid
            or info.st_gid != gid
            or info.st_mode & 0o077
        ):
            raise SourceSnapshotError("snapshot directory ownership is unsafe")


def _validate_requested_owner(uid: int) -> None:
    if os.geteuid() != 0 and uid != os.getuid():
        raise SourceSnapshotError("cannot create a snapshot for another host user")


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        offset += os.write(fd, payload[offset:])


def _lfs_state(has_lfs: bool, pointers: bool, hydrated: bool) -> str:
    if not has_lfs:
        return "none"
    if pointers and hydrated:
        return "mixed"
    if pointers:
        return "pointers"
    return "hydrated"


__all__ = ["canonical_snapshot_hash", "create_source_snapshot"]
