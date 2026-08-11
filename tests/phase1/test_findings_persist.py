"""FR-FINDINGS-PERSIST tests.

Verifies that scanner findings and raw scanner artifacts persist durably in
SQLite via the repository layer: bulk-inserted findings can be queried back
with severity filters and counts; raw artifacts are stored gzip-compressed
with a content hash, and decompress to the original bytes.
"""
from __future__ import annotations

import hashlib

from server.db.repositories.findings import FindingRepository
from server.db.repositories.scanner_artifacts import ScannerArtifactRepository


# ---------------------------------------------------------------------------
# FindingRepository
# ---------------------------------------------------------------------------

async def test_bulk_insert_then_list_roundtrip(session) -> None:
    """Inserted findings come back via list_for_run with all fields intact."""
    repo = FindingRepository(session)
    items = [
        {
            "run_id": "run-1",
            "scanner_kind": "semgrep",
            "rule_id": "rule-a",
            "severity": "HIGH",
            "file_path": "src/main.py",
            "line_start": 10,
            "line_end": 12,
            "message": "Bad thing",
            "theme": "injection",
            "fix_strategy": None,
            "compliance_tags": ["CWE-78", "OWASP-A1"],
            "raw_index": 0,
        },
        {
            "run_id": "run-1",
            "scanner_kind": "gitleaks",
            "rule_id": "secret-detected",
            "severity": "MEDIUM",
            "file_path": ".env",
            "line_start": 1,
            "line_end": None,
            "message": "Committed secret",
            "theme": "secrets",
            "fix_strategy": "single-file",
            "compliance_tags": [],
            "raw_index": 1,
        },
    ]
    inserted = await repo.bulk_insert(items)
    assert inserted == 2

    rows = await repo.list_for_run("run-1")
    assert len(rows) == 2
    # Severity ordering: HIGH sorts before MEDIUM (lexicographic on the enum).
    assert rows[0].severity == "HIGH"
    assert rows[0].rule_id == "rule-a"
    assert rows[0].message == "Bad thing"
    assert rows[1].severity == "MEDIUM"


async def test_list_for_run_filters_by_severity(session) -> None:
    """Severity filter narrows the result set to matching rows only."""
    repo = FindingRepository(session)
    await repo.bulk_insert([
        {"run_id": "r", "scanner_kind": "s", "severity": "HIGH", "message": "h", "compliance_tags": []},
        {"run_id": "r", "scanner_kind": "s", "severity": "MEDIUM", "message": "m", "compliance_tags": []},
        {"run_id": "r", "scanner_kind": "s", "severity": "MEDIUM", "message": "m2", "compliance_tags": []},
        {"run_id": "r", "scanner_kind": "s", "severity": "LOW", "message": "l", "compliance_tags": []},
    ])
    highs = await repo.list_for_run("r", severity="high")  # case-insensitive
    assert len(highs) == 1
    assert highs[0].severity == "HIGH"
    mediums = await repo.list_for_run("r", severity="MEDIUM")
    assert len(mediums) == 2


async def test_list_for_run_isolates_by_run_id(session) -> None:
    """Findings from one run don't leak into another run's listing."""
    repo = FindingRepository(session)
    await repo.bulk_insert([
        {"run_id": "run-A", "scanner_kind": "s", "severity": "HIGH", "message": "a", "compliance_tags": []},
        {"run_id": "run-B", "scanner_kind": "s", "severity": "HIGH", "message": "b", "compliance_tags": []},
    ])
    a_rows = await repo.list_for_run("run-A")
    b_rows = await repo.list_for_run("run-B")
    assert len(a_rows) == 1 and a_rows[0].run_id == "run-A"
    assert len(b_rows) == 1 and b_rows[0].run_id == "run-B"


async def test_count_for_run_returns_total(session) -> None:
    """count_for_run returns the total number of findings regardless of severity."""
    repo = FindingRepository(session)
    await repo.bulk_insert([
        {"run_id": "r", "scanner_kind": "s", "severity": sev, "message": msg, "compliance_tags": []}
        for sev, msg in [("HIGH", "a"), ("HIGH", "b"), ("MEDIUM", "c"), ("LOW", "d")]
    ])
    assert await repo.count_for_run("r") == 4
    assert await repo.count_for_run("other") == 0


async def test_bulk_insert_empty_returns_zero(session) -> None:
    """No-op when nothing to insert."""
    repo = FindingRepository(session)
    assert await repo.bulk_insert([]) == 0


# ---------------------------------------------------------------------------
# ScannerArtifactRepository — gzip-compressed raw output
# ---------------------------------------------------------------------------

async def test_artifact_store_and_decompress_roundtrip(session) -> None:
    """Raw scanner output (bytes) survives the gzip compress/decompress cycle
    and the stored content_hash matches the original.
    """
    repo = ScannerArtifactRepository(session)
    original = b'{"results": [{"rule": "x", "message": "hi"}]}' * 50  # repetitive → compresses well
    artifact = await repo.store(scanner_run_id=42, kind="json", content=original)

    assert artifact.kind == "json"
    assert artifact.size_bytes == len(original)
    assert artifact.content_hash == f"sha256:{hashlib.sha256(original).hexdigest()}"
    # Gzip should give us meaningful compression on the repetitive payload.
    assert len(artifact.content_blob) < len(original)

    fetched = await repo.get_for_scanner_run(42)
    assert fetched is not None
    assert ScannerArtifactRepository.decompress(fetched) == original


async def test_artifact_get_for_unknown_scanner_run_returns_none(session) -> None:
    repo = ScannerArtifactRepository(session)
    assert await repo.get_for_scanner_run(9999) is None
