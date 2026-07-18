#!/usr/bin/env python3
"""Discover native project tests and write a scan-time inventory."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".assurance-scan",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    ".next",
    ".turbo",
    "__pycache__",
}

TEST_FILE_RE = re.compile(
    r"(^|/)(__tests__|tests?|spec|e2e|integration|unit|load)(/|$)|"
    r"(\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs|py|java|go|rs)$)|"
    r"(^test_.*\.py$|_test\.go$)"
)
JS_CASE_RE = re.compile(r"\b(?:it|test)\s*\(\s*(['\"`])(?P<name>.+?)\1")
PY_CASE_RE = re.compile(r"^\s*def\s+(?P<name>test_[A-Za-z0-9_]+)\s*\(", re.MULTILINE)


def classify(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    text = str(path).lower()
    if "e2e" in parts or "playwright" in text or "cypress" in text:
        return "e2e"
    if "load" in parts or "k6" in text or "locust" in text:
        return "load"
    if "integration" in parts or "integ" in parts:
        return "integration"
    if "unit" in parts:
        return "unit"
    return "unit"


def extract_cases(path: Path, rel: str) -> list[dict]:
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return []
    cases: list[dict] = []
    if path.suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        for match in JS_CASE_RE.finditer(text):
            name = " ".join(match.group("name").split())
            if name:
                cases.append({"name": name, "ref": f"{rel}::{name}"})
    elif path.suffix == ".py":
        for match in PY_CASE_RE.finditer(text):
            name = match.group("name")
            cases.append({"name": name, "ref": f"{rel}::{name}"})
    return cases[:200]


def discover(target_dir: Path) -> dict:
    files: list[dict] = []
    counts = {"unit": 0, "integration": 0, "e2e": 0, "load": 0}
    case_count = 0
    for root_str, dirs, names in os.walk(target_dir):
        root = Path(root_str)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".venv")]
        for name in names:
            path = root / name
            try:
                rel = str(path.relative_to(target_dir))
            except ValueError:
                rel = str(path)
            rel_posix = rel.replace("\\", "/")
            if not TEST_FILE_RE.search(rel_posix):
                continue
            test_type = classify(Path(rel_posix))
            cases = extract_cases(path, rel_posix)
            case_count += len(cases)
            counts[test_type] = counts.get(test_type, 0) + 1
            files.append({
                "path": rel_posix,
                "type": test_type,
                "framework": infer_framework(path, rel_posix),
                "cases": cases,
                "status": "discovered",
            })
    files.sort(key=lambda item: item["path"])
    return {
        "version": 1,
        "target_dir": str(target_dir),
        "summary": {
            "files": len(files),
            "cases": case_count,
            "by_type": counts,
        },
        "files": files,
        "note": "Discovered tests prove test assets exist. Exported JUnit results are required to prove execution/pass-fail evidence.",
    }


def infer_framework(path: Path, rel: str) -> str:
    suffix = path.suffix.lower()
    lower = rel.lower()
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        if "playwright" in lower:
            return "playwright"
        if "cypress" in lower:
            return "cypress"
        return "jest/vitest"
    if suffix == ".py":
        return "pytest/unittest"
    if suffix == ".go":
        return "go test"
    if suffix == ".rs":
        return "cargo test"
    if suffix == ".java":
        return "junit"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target_dir = Path(args.target_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(discover(target_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
