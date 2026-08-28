#!/usr/bin/env python3
"""Check source files, including untracked files, for repository hygiene issues."""

from __future__ import annotations

import os
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIRECTORIES = {
    ".assurance-scan",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svelte-kit",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "reports",
}
EXCLUDED_RELATIVE_ROOTS = (
    Path("backend/resources/authority-sources/raw"),
    Path("backend/resources/compliance-packs"),
)
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".svelte",
    ".toml",
    ".ts",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {"Dockerfile", ".dockerignore", ".gitignore"}
CONFLICT_MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")


def _source_files() -> list[Path]:
    files: list[Path] = []
    for root, directories, names in os.walk(REPOSITORY_ROOT):
        directories[:] = sorted(name for name in directories if name not in EXCLUDED_DIRECTORIES)
        root_path = Path(root)
        for name in sorted(names):
            path = root_path / name
            relative = path.relative_to(REPOSITORY_ROOT)
            if any(relative.is_relative_to(excluded) for excluded in EXCLUDED_RELATIVE_ROOTS):
                continue
            if (
                name in TEXT_FILENAMES
                or name.startswith("Dockerfile")
                or path.suffix.lower() in TEXT_SUFFIXES
            ):
                files.append(path)
    return files


def main() -> int:
    violations: list[str] = []
    for path in _source_files():
        relative = path.relative_to(REPOSITORY_ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            violations.append(f"{relative}: not valid UTF-8")
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip(" \t") != line:
                violations.append(f"{relative}:{line_number}: trailing whitespace")
            if line.startswith(CONFLICT_MARKERS):
                violations.append(f"{relative}:{line_number}: unresolved merge marker")
        if text and not text.endswith("\n"):
            violations.append(f"{relative}: missing final newline")

    if violations:
        print("Source hygiene violations:")
        print("\n".join(violations))
        return 1
    print(f"Source hygiene passed: {len(_source_files())} text files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
