#!/usr/bin/env python3
"""Canonical JSON and artifact hashing helpers.

These helpers are intentionally small and dependency-free because they sit on
the audit/proof path. Callers can choose raw hex digests for plain manifest
entries or `sha256:<hex>` commitments for graph/proof artifacts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


HASH_PREFIX = "sha256:"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_json_sha256(value: Any, *, prefixed: bool = True) -> str:
    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return f"{HASH_PREFIX}{digest}" if prefixed else digest


def file_sha256(path: Path | None, *, prefixed: bool = False) -> str:
    if not path or not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    digest = h.hexdigest()
    return f"{HASH_PREFIX}{digest}" if prefixed else digest


def ensure_sha256_prefix(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    return value if value.startswith(HASH_PREFIX) else f"{HASH_PREFIX}{value}"


def report_hash_filename(rel: str | Path) -> str:
    return "__".join(Path(rel).parts) + ".sha256"


def write_hash_sidecar(report_dir: Path, artifact: Path) -> None:
    if not artifact.exists() or not artifact.is_file():
        return
    rel = artifact.relative_to(report_dir)
    hashes_dir = report_dir / "hashes"
    hashes_dir.mkdir(parents=True, exist_ok=True)
    (hashes_dir / report_hash_filename(rel)).write_text(f"{file_sha256(artifact)}  {rel}\n")
