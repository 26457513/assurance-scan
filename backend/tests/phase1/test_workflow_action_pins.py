"""Supply-chain checks for GitHub Actions references shipped by the project."""

from __future__ import annotations

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
USES_PATTERN = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^\s'\"#]+)", re.MULTILINE)
FULL_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def _workflow_files() -> list[Path]:
    files = sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml"))
    files.extend(sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yaml")))
    files.append(REPOSITORY_ROOT / "backend" / "resources" / "templates" / "assurance-scan.yml")
    return files


def test_external_workflow_actions_are_pinned_to_commit_shas() -> None:
    violations: list[str] = []
    for path in _workflow_files():
        assert path.is_file(), f"expected workflow file is missing: {path}"
        for reference in USES_PATTERN.findall(path.read_text(encoding="utf-8")):
            if reference.startswith(("./", "docker://")):
                continue
            _, separator, revision = reference.rpartition("@")
            if not separator or not FULL_COMMIT_SHA.fullmatch(revision):
                violations.append(f"{path.relative_to(REPOSITORY_ROOT)}: {reference}")

    assert violations == [], "mutable GitHub Actions references:\n" + "\n".join(violations)
