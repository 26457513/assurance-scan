"""Tribal checks: repo-defined declarative assertions, evaluated at scan time.

A repo drops `tribal-checks.json` at its root; the orchestrator evaluates
each check against the working tree and emits findings through the normal
pipeline (scanner_kind="tribal"). Checks are declarative — a fixed
vocabulary of types interpreted here, never executed — so the file is safe
to honour on any push.
"""
from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.worker.parsers.base import ParsedFinding

TRIBAL_FILENAME = "tribal-checks.json"

# Guards against pathological content scans (also bounds ReDoS exposure).
MAX_FILE_SCAN_BYTES = 2_000_000
MAX_FILES_PER_GLOB = 20_000
# Line counting is safe on big files; only I/O bounds it.
MAX_LINECOUNT_BYTES = 20_000_000

VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
VALID_TYPES = {
    "file_exists",
    "file_absent",
    "file_max_size",
    "file_max_lines",
    "content_forbidden",
    "content_required",
    "file_count",
}


class TribalCheckError(Exception):
    """Raised on a malformed tribal-checks.json."""


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    severity: str
    type: str
    params: dict[str, Any]


def load_checks(project_root: Path) -> list[Check]:
    path = project_root / TRIBAL_FILENAME
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TribalCheckError(f"invalid {TRIBAL_FILENAME}: {exc}") from exc

    raw = doc.get("checks")
    if not isinstance(raw, list):
        raise TribalCheckError(f"{TRIBAL_FILENAME}: 'checks' must be a list")

    checks: list[Check] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise TribalCheckError(f"checks[{i}]: must be an object")
        cid = entry.get("id")
        ctype = entry.get("type")
        if not isinstance(cid, str) or not cid:
            raise TribalCheckError(f"checks[{i}]: 'id' is required")
        if cid in seen:
            raise TribalCheckError(f"checks[{i}]: duplicate id {cid!r}")
        seen.add(cid)
        if ctype not in VALID_TYPES:
            raise TribalCheckError(
                f"checks[{i}] ({cid}): unknown type {ctype!r}; "
                f"valid: {sorted(VALID_TYPES)}"
            )
        severity = str(entry.get("severity", "MEDIUM")).upper()
        if severity not in VALID_SEVERITIES:
            raise TribalCheckError(
                f"checks[{i}] ({cid}): bad severity {severity!r}; "
                f"valid: {sorted(VALID_SEVERITIES)}"
            )
        checks.append(Check(
            id=cid,
            title=str(entry.get("title", cid)),
            severity=severity,
            type=ctype,
            params={k: v for k, v in entry.items()
                    if k not in ("id", "title", "severity", "type")},
        ))
    return checks


def _match_any(path: Path, root: Path, patterns: list[str]) -> bool:
    rel = path.relative_to(root).as_posix()
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        # "**/x" should also match a top-level "x" (fnmatch has no **).
        if pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]):
            return True
    return False


def _glob_files(root: Path, pattern: str, exclude: list[str]) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if len(files) >= MAX_FILES_PER_GLOB:
            break
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if rel_parts and rel_parts[0] == ".git":
            continue
        if _match_any(path, root, [pattern]) and not _match_any(path, root, exclude):
            files.append(path)
    return files


def _read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > MAX_FILE_SCAN_BYTES or b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def _count_lines(path: Path) -> int | None:
    """Line count on raw bytes; None for binaries or files past the ceiling."""
    try:
        with path.open("rb") as fh:
            head = fh.read(8192)
            if b"\0" in head:
                return None
            n = head.count(b"\n")
            while chunk := fh.read(1 << 20):
                n += chunk.count(b"\n")
                if fh.tell() > MAX_LINECOUNT_BYTES:
                    return None
            return n
    except OSError:
        return None


def _finding(check: Check, message: str, file_path: str | None = None,
             line: int | None = None) -> ParsedFinding:
    return ParsedFinding(
        scanner_kind="tribal",
        rule_id=check.id,
        severity=check.severity,
        file_path=file_path,
        line_start=line,
        line_end=line,
        message=f"{check.title}: {message}",
        theme="tribal",
        fix_strategy=None,
        compliance_tags=(),
    )


def run_checks(project_root: Path, checks: list[Check]) -> list[ParsedFinding]:
    findings: list[ParsedFinding] = []
    for check in checks:
        try:
            findings.extend(_run_one(project_root, check))
        except TribalCheckError:
            raise
        except Exception as exc:  # a bad check must not kill the scan
            findings.append(_finding(check, f"check errored: {exc}"))
    return findings


def _run_one(root: Path, check: Check) -> list[ParsedFinding]:
    p = check.params
    out: list[ParsedFinding] = []

    if check.type == "file_exists":
        for rel in p.get("paths", [] if "paths" in p else [p.get("path")]):
            if not rel:
                raise TribalCheckError(f"{check.id}: 'path' or 'paths' required")
            if not (root / rel).exists():
                out.append(_finding(check, f"required file missing: {rel}", rel))

    elif check.type == "file_absent":
        for rel in p.get("paths", [] if "paths" in p else [p.get("path")]):
            if not rel:
                raise TribalCheckError(f"{check.id}: 'path' or 'paths' required")
            target = root / rel
            if target.exists():
                out.append(_finding(check, f"forbidden file present: {rel}", rel))

    elif check.type == "file_max_size":
        glob = p.get("glob", "**/*")
        if "max_kb" not in p:
            raise TribalCheckError(f"{check.id}: 'max_kb' required")
        limit = int(p["max_kb"]) * 1024
        exclude = p.get("exclude", [])
        for f in _glob_files(root, glob, exclude):
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if size > limit:
                rel = f.relative_to(root).as_posix()
                out.append(_finding(
                    check, f"{rel} is {size // 1024} KB (limit {limit // 1024} KB)", rel))

    elif check.type == "file_max_lines":
        glob = p.get("glob", "**/*")
        if "max_lines" not in p:
            raise TribalCheckError(f"{check.id}: 'max_lines' required")
        limit = int(p["max_lines"])
        exclude = p.get("exclude", [])
        for f in _glob_files(root, glob, exclude):
            n = _count_lines(f)
            if n is None:
                continue
            if n > limit:
                rel = f.relative_to(root).as_posix()
                out.append(_finding(
                    check, f"{rel} has {n} lines (limit {limit})", rel))

    elif check.type in ("content_forbidden", "content_required"):
        glob = p.get("glob", "**/*")
        pattern = p.get("pattern")
        if not pattern:
            raise TribalCheckError(f"{check.id}: 'pattern' required")
        regex = re.compile(pattern)
        exclude = p.get("exclude", [])
        for f in _glob_files(root, glob, exclude):
            text = _read_text(f)
            if text is None:
                continue
            rel = f.relative_to(root).as_posix()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    if check.type == "content_forbidden":
                        out.append(_finding(check, f"forbidden pattern in {rel}", rel, lineno))
                    else:
                        break  # content_required: one hit satisfies the file
            else:
                if check.type == "content_required":
                    out.append(_finding(check, f"pattern not found in {rel}", rel))

    elif check.type == "file_count":
        glob = p.get("glob", "*")
        exclude = p.get("exclude", [])
        count = len(_glob_files(root, glob, exclude))
        if "min" in p and count < int(p["min"]):
            out.append(_finding(
                check, f"{count} files match {glob!r}; minimum {p['min']}"))
        if "max" in p and count > int(p["max"]):
            out.append(_finding(
                check, f"{count} files match {glob!r}; maximum {p['max']}"))

    return out
