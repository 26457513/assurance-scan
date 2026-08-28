"""Owner-only outbox persistence, locking, retry updates, and safe pruning."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Mapping

from .models import (
    OutboxEntry,
    OutboxLockedError,
    OutboxRecord,
    OutboxState,
    OutboxStorageError,
    PruneResult,
)


DEFAULT_RETENTION = timedelta(days=7)
DEFAULT_QUOTA_BYTES = 1024 * 1024 * 1024
_RECORD = "record.json"
_LOCK = ".lock"


class OutboxStore:
    """Filesystem adapter with request-scoped locks and no background daemon."""

    def __init__(
        self,
        root: Path,
        *,
        expected_uid: int | None = None,
        expected_gid: int | None = None,
    ) -> None:
        self.root = root
        self.expected_uid = os.getuid() if expected_uid is None else expected_uid
        self.expected_gid = os.getgid() if expected_gid is None else expected_gid
        _validate_requested_owner(self.expected_uid)
        _ensure_directory(root, self.expected_uid, self.expected_gid)

    def save(
        self,
        request_id: str,
        artifacts: Mapping[str, bytes],
        *,
        now: datetime | None = None,
    ) -> OutboxEntry:
        """Persist a complete retry bundle before its first upload attempt."""
        canonical_id = _request_id(request_id)
        if not artifacts:
            raise OutboxStorageError("outbox bundle must contain artifacts")
        names = tuple(sorted(_artifact_name(name) for name in artifacts))
        request_path = self.root / canonical_id
        request_path.mkdir(mode=0o700)
        os.chown(request_path, self.expected_uid, self.expected_gid)
        os.chmod(request_path, 0o700)
        try:
            with self.lock(canonical_id):
                total = 0
                for name in names:
                    payload = artifacts[name]
                    if not isinstance(payload, bytes):
                        raise OutboxStorageError("outbox artifacts must be bytes")
                    _atomic_write(request_path / name, payload, self.expected_uid, self.expected_gid)
                    total += len(payload)
                timestamp = _utc(now)
                record = OutboxRecord(
                    request_id=canonical_id,
                    state=OutboxState.PENDING,
                    created_at=timestamp,
                    updated_at=timestamp,
                    total_bytes=total,
                )
                _write_record(request_path, record, self.expected_uid, self.expected_gid)
                return OutboxEntry(record=record, path=request_path, artifact_names=names)
        except Exception:
            shutil.rmtree(request_path, ignore_errors=True)
            raise

    def load(self, request_id: str) -> OutboxEntry:
        """Load a retained retry record after validating owner-only content."""
        path = self.root / _request_id(request_id)
        _validate_directory(path, self.expected_uid, self.expected_gid)
        record = _read_record(path / _RECORD, self.expected_uid, self.expected_gid)
        if record.request_id != path.name:
            raise OutboxStorageError("outbox record does not match its request directory")
        names_list: list[str] = []
        for child in path.iterdir():
            if child.name in (_RECORD, _LOCK):
                continue
            if not _is_safe_file(child, self.expected_uid, self.expected_gid):
                raise OutboxStorageError("outbox contains an unsafe artifact")
            names_list.append(_artifact_name(child.name))
        names = tuple(sorted(names_list))
        return OutboxEntry(record=record, path=path, artifact_names=names)

    def read_artifacts(self, request_id: str) -> dict[str, bytes]:
        """Read a complete retry bundle under its request lock."""
        with self.lock(request_id):
            entry = self.load(request_id)
            return {
                name: _read_safe_file(
                    entry.path / name,
                    self.expected_uid,
                    self.expected_gid,
                    entry.record.total_bytes,
                )
                for name in entry.artifact_names
            }

    def update_retry(
        self,
        request_id: str,
        *,
        retryable: bool,
        error_code: str,
        now: datetime | None = None,
    ) -> OutboxEntry:
        """Record upload disposition while retaining the exact same bundle."""
        if not error_code or len(error_code) > 128 or any(character.isspace() for character in error_code):
            raise OutboxStorageError("outbox error code is invalid")
        with self.lock(request_id):
            entry = self.load(request_id)
            record = OutboxRecord(
                request_id=entry.record.request_id,
                state=OutboxState.RETRYABLE if retryable else OutboxState.PERMANENT_REJECTION,
                created_at=entry.record.created_at,
                updated_at=_utc(now),
                total_bytes=entry.record.total_bytes,
                last_error_code=error_code,
            )
            _write_record(entry.path, record, self.expected_uid, self.expected_gid)
            return OutboxEntry(record=record, path=entry.path, artifact_names=entry.artifact_names)

    def mark_uploaded(
        self,
        request_id: str,
        *,
        run_url: str,
        now: datetime | None = None,
    ) -> OutboxEntry:
        """Delete sensitive bundle files and retain only a small receipt."""
        with self.lock(request_id):
            entry = self.load(request_id)
            for name in entry.artifact_names:
                (entry.path / name).unlink()
            record = OutboxRecord(
                request_id=entry.record.request_id,
                state=OutboxState.UPLOADED,
                created_at=entry.record.created_at,
                updated_at=_utc(now),
                total_bytes=0,
                run_url=run_url,
            )
            _write_record(entry.path, record, self.expected_uid, self.expected_gid)
            return OutboxEntry(record=record, path=entry.path, artifact_names=())

    def list(self) -> tuple[OutboxEntry, ...]:
        entries: list[OutboxEntry] = []
        for child in self.root.iterdir():
            if child.name.startswith("."):
                continue
            try:
                entries.append(self.load(child.name))
            except (OutboxStorageError, ValueError):
                continue
        return tuple(sorted(entries, key=lambda item: item.record.created_at))

    def prune(
        self,
        *,
        now: datetime | None = None,
        retention: timedelta = DEFAULT_RETENTION,
        quota_bytes: int = DEFAULT_QUOTA_BYTES,
    ) -> PruneResult:
        """Remove expired/oldest bundles, always skipping active request locks."""
        timestamp = _utc(now)
        entries = list(self.list())
        retained = sum(entry.record.total_bytes for entry in entries)
        removed: list[str] = []
        skipped: list[str] = []
        expired = {entry.record.request_id for entry in entries if timestamp - entry.record.updated_at > retention}
        for entry in entries:
            should_remove = entry.record.request_id in expired or retained > quota_bytes
            if not should_remove:
                continue
            try:
                with self.lock(entry.record.request_id, blocking=False):
                    shutil.rmtree(entry.path)
                    retained -= entry.record.total_bytes
                    removed.append(entry.record.request_id)
            except OutboxLockedError:
                skipped.append(entry.record.request_id)
        return PruneResult(tuple(removed), tuple(skipped), retained)

    @contextmanager
    def lock(self, request_id: str, *, blocking: bool = True) -> Iterator[None]:
        canonical_id = _request_id(request_id)
        request_path = self.root / canonical_id
        _validate_directory(request_path, self.expected_uid, self.expected_gid)
        lock_path = request_path / _LOCK
        lock_existed = lock_path.exists() or lock_path.is_symlink()
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        try:
            if not lock_existed:
                os.fchown(fd, self.expected_uid, self.expected_gid)
                os.fchmod(fd, 0o600)
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.expected_uid
                or info.st_gid != self.expected_gid
                or info.st_mode & 0o077
            ):
                raise OutboxStorageError("outbox lock is unsafe")
            operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(fd, operation)
            except BlockingIOError as exc:
                raise OutboxLockedError(f"outbox request is active: {canonical_id}") from exc
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _write_record(path: Path, record: OutboxRecord, uid: int, gid: int) -> None:
    document = {
        "request_id": record.request_id,
        "state": record.state.value,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "total_bytes": record.total_bytes,
        "last_error_code": record.last_error_code,
        "run_url": record.run_url,
    }
    _atomic_write(
        path / _RECORD,
        (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        uid,
        gid,
    )


def _read_record(path: Path, uid: int, gid: int) -> OutboxRecord:
    try:
        document = json.loads(
            _read_safe_file(path, uid, gid, 128 * 1024).decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
        record = OutboxRecord(
            request_id=_request_id(document["request_id"]),
            state=OutboxState(document["state"]),
            created_at=datetime.fromisoformat(document["created_at"]),
            updated_at=datetime.fromisoformat(document["updated_at"]),
            total_bytes=int(document["total_bytes"]),
            last_error_code=document.get("last_error_code"),
            run_url=document.get("run_url"),
        )
        if record.total_bytes < 0 or record.created_at.tzinfo is None or record.updated_at.tzinfo is None:
            raise OutboxStorageError("outbox record has invalid values")
        return record
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OutboxStorageError("outbox record is invalid") from exc


def _atomic_write(path: Path, payload: bytes, uid: int, gid: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchown(fd, uid, gid)
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if fd >= 0:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        raise


def _request_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise OutboxStorageError("request ID must be a canonical lowercase UUIDv4") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise OutboxStorageError("request ID must be a canonical lowercase UUIDv4")
    return value


def _artifact_name(value: str) -> str:
    if (
        not value
        or value in (".", "..", _RECORD, _LOCK)
        or value.startswith(".")
        or Path(value).name != value
        or "\\" in value
        or "\x00" in value
    ):
        raise OutboxStorageError("outbox artifact name is invalid")
    return value


def _validate_directory(path: Path, uid: int, gid: int) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise OutboxStorageError("outbox directory is unavailable") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != uid
        or info.st_gid != gid
        or info.st_mode & 0o077
    ):
        raise OutboxStorageError("outbox directory must be owner-only and symlink-free")


def _is_safe_file(path: Path, uid: int, gid: int) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and not stat.S_ISLNK(info.st_mode)
        and info.st_uid == uid
        and info.st_gid == gid
        and not info.st_mode & 0o077
    )


def _read_safe_file(path: Path, uid: int, gid: int, maximum: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise OutboxStorageError("outbox file cannot be opened safely") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != uid
            or info.st_gid != gid
            or info.st_mode & 0o077
        ):
            raise OutboxStorageError("outbox file is unsafe")
        result = bytearray()
        while True:
            chunk = os.read(fd, min(1024 * 1024, maximum + 1 - len(result)))
            if not chunk:
                return bytes(result)
            result.extend(chunk)
            if len(result) > maximum:
                raise OutboxStorageError("outbox file exceeds its recorded bounds")
    finally:
        os.close(fd)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise OutboxStorageError("outbox record contains a duplicate key")
        result[key] = value
    return result


def _utc(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise OutboxStorageError("outbox timestamps must be timezone-aware")
    return result.astimezone(timezone.utc)


def _ensure_directory(path: Path, uid: int, gid: int) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        if current.is_symlink():
            raise OutboxStorageError("outbox path must not contain symlinks")
        missing.append(current)
        current = current.parent
    _validate_directory(current, uid, gid)
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        os.chown(directory, uid, gid)
        os.chmod(directory, 0o700)
    _validate_directory(path, uid, gid)


def _validate_requested_owner(uid: int) -> None:
    if os.geteuid() != 0 and uid != os.getuid():
        raise OutboxStorageError("cannot create an outbox for another host user")


__all__ = ["DEFAULT_QUOTA_BYTES", "DEFAULT_RETENTION", "OutboxStore"]
