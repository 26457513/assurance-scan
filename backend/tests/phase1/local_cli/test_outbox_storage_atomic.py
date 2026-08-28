from __future__ import annotations

import stat
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.modules.atomic.local_cli.outbox_storage import OutboxState, OutboxStorageError, OutboxStore


def _store(tmp_path: Path) -> OutboxStore:
    root = tmp_path / "outbox"
    return OutboxStore(root)


def test_save_retry_and_upload_receipt_are_owner_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    request_id = str(uuid.uuid4())
    entry = store.save(request_id, {"metadata.json": b"{}", "findings.json": b"[]"})
    assert entry.record.state is OutboxState.PENDING
    assert stat.S_IMODE(entry.path.stat().st_mode) == 0o700
    assert (entry.path.stat().st_uid, entry.path.stat().st_gid) == (os.getuid(), os.getgid())
    assert all(stat.S_IMODE((entry.path / name).stat().st_mode) == 0o600 for name in entry.artifact_names)
    assert store.read_artifacts(request_id) == {"findings.json": b"[]", "metadata.json": b"{}"}

    retry = store.update_retry(request_id, retryable=True, error_code="network_error")
    assert retry.record.state is OutboxState.RETRYABLE
    assert retry.record.last_error_code == "network_error"
    uploaded = store.mark_uploaded(request_id, run_url="https://scan.example/scans/local-1")
    assert uploaded.record.state is OutboxState.UPLOADED
    assert uploaded.artifact_names == ()
    assert store.load(request_id).record.run_url.endswith("local-1")


def test_prune_enforces_seven_days_and_quota_oldest_first(tmp_path: Path) -> None:
    store = _store(tmp_path)
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    old = str(uuid.uuid4())
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    store.save(old, {"findings.json": b"x" * 5}, now=now - timedelta(days=8))
    store.save(first, {"findings.json": b"x" * 7}, now=now - timedelta(days=2))
    store.save(second, {"findings.json": b"x" * 11}, now=now - timedelta(days=1))
    result = store.prune(now=now, quota_bytes=12)
    assert result.removed_request_ids == (old, first)
    assert result.retained_bytes == 11
    assert store.load(second).record.total_bytes == 11


def test_prune_skips_active_request_lock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    store.save(request_id, {"findings.json": b"sensitive"}, now=now - timedelta(days=8))
    with store.lock(request_id):
        result = store.prune(now=now)
    assert result.skipped_locked_request_ids == (request_id,)
    assert store.load(request_id).artifact_names == ("findings.json",)


def test_save_rejects_artifact_path_traversal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(OutboxStorageError, match="artifact name"):
        store.save(str(uuid.uuid4()), {"..": b"escape"})


def test_non_root_process_cannot_claim_another_host_identity(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root is allowed to assign the mounted host identity")
    with pytest.raises(OutboxStorageError, match="another host user"):
        OutboxStore(tmp_path / "foreign", expected_uid=os.getuid() + 1, expected_gid=os.getgid())
