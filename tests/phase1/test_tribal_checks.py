"""Tests for tribal checks (repo-defined declarative assertions)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.worker.tribal import (
    TribalCheckError,
    load_checks,
    run_checks,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "big.bin").write_bytes(b"x" * 2048)
    (tmp_path / "small.txt").write_text("hello\nTODO fix this\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    return tmp_path


def _write(root: Path, checks: list[dict]) -> Path:
    (root / "tribal-checks.json").write_text(json.dumps({"checks": checks}))
    return root


def test_no_file_means_no_checks(repo: Path) -> None:
    assert load_checks(repo) == []


def test_file_exists_and_absent(repo: Path) -> None:
    _write(repo, [
        {"id": "need", "type": "file_exists", "path": "missing.md"},
        {"id": "ban", "type": "file_absent", "path": "small.txt"},
    ])
    findings = run_checks(repo, load_checks(repo))
    assert {f.rule_id for f in findings} == {"need", "ban"}
    assert findings[0].scanner_kind == "tribal"


def test_max_size_with_exclude(repo: Path) -> None:
    _write(repo, [{"id": "sz", "type": "file_max_size", "glob": "**/*",
                   "max_kb": 1, "exclude": ["src/**"]}])
    findings = run_checks(repo, load_checks(repo))
    assert len(findings) == 1
    assert findings[0].file_path == "big.bin"
    assert "2 KB" in findings[0].message


def test_content_forbidden_line_anchored(repo: Path) -> None:
    _write(repo, [{"id": "todo", "type": "content_forbidden",
                   "glob": "**/*.txt", "pattern": "TODO"}])
    findings = run_checks(repo, load_checks(repo))
    assert len(findings) == 1
    assert findings[0].file_path == "small.txt"
    assert findings[0].line_start == 2


def test_content_required(repo: Path) -> None:
    _write(repo, [{"id": "hdr", "type": "content_required",
                   "glob": "**/*.txt", "pattern": "Copyright"}])
    findings = run_checks(repo, load_checks(repo))
    assert len(findings) == 1
    assert "not found" in findings[0].message


def test_file_count_bounds(repo: Path) -> None:
    _write(repo, [{"id": "py", "type": "file_count", "glob": "**/*.py", "min": 2}])
    findings = run_checks(repo, load_checks(repo))
    assert len(findings) == 1
    assert "minimum 2" in findings[0].message


def test_bad_type_rejected(repo: Path) -> None:
    _write(repo, [{"id": "x", "type": "run_arbitrary_code"}])
    with pytest.raises(TribalCheckError, match="unknown type"):
        load_checks(repo)


def test_bad_severity_rejected(repo: Path) -> None:
    _write(repo, [{"id": "x", "type": "file_exists", "path": "a", "severity": "URGENT"}])
    with pytest.raises(TribalCheckError, match="bad severity"):
        load_checks(repo)


def test_duplicate_ids_rejected(repo: Path) -> None:
    _write(repo, [
        {"id": "x", "type": "file_exists", "path": "a"},
        {"id": "x", "type": "file_exists", "path": "b"},
    ])
    with pytest.raises(TribalCheckError, match="duplicate"):
        load_checks(repo)


def test_malformed_json_rejected(repo: Path) -> None:
    (repo / "tribal-checks.json").write_text("{nope")
    with pytest.raises(TribalCheckError):
        load_checks(repo)


def test_check_error_becomes_finding_not_crash(repo: Path) -> None:
    checks_doc = [{"id": "bad", "type": "file_max_size", "glob": "**/*", "max_kb": "not-a-number"}]
    _write(repo, checks_doc)
    parsed = load_checks(repo)
    findings = run_checks(repo, parsed)
    assert len(findings) == 1
    assert "check errored" in findings[0].message


def test_file_max_lines(repo: Path) -> None:
    (repo / "big.py").write_text("x = 1\n" * 50)
    (repo / "small.py").write_text("x = 1\n")
    _write(repo, [{"id": "lines", "type": "file_max_lines", "glob": "**/*.py", "max_lines": 40}])
    findings = run_checks(repo, load_checks(repo))
    assert len(findings) == 1
    assert findings[0].file_path == "big.py"
    assert "50 lines" in findings[0].message


def test_file_max_lines_counts_files_past_content_scan_cap(repo: Path) -> None:
    # 2.1MB of text: past _read_text's 2MB cap, still line-counted.
    (repo / "huge.py").write_bytes(b"x" * 2097150 + b"\n\n\n")
    _write(repo, [{"id": "lines", "type": "file_max_lines", "glob": "**/*.py", "max_lines": 2}])
    findings = run_checks(repo, load_checks(repo))
    assert len(findings) == 1
    assert findings[0].file_path == "huge.py"
