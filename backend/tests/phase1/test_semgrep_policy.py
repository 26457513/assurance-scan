"""Regression checks for the deterministic repository-local Semgrep policy."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
NOSEMGREP = re.compile(r"nosemgrep(?::\s*([A-Za-z0-9._-]+))?\s*$")


def _policy_rule_ids() -> set[str]:
    policy = yaml.safe_load((BACKEND_ROOT / "semgrep.yml").read_text())
    return {rule["id"] for rule in policy["rules"]}


def test_python_nosemgrep_exceptions_are_rule_specific_and_locally_defined() -> None:
    rule_ids = _policy_rule_ids()
    exceptions: list[tuple[Path, int, str | None]] = []
    for source_root in (BACKEND_ROOT / "app", BACKEND_ROOT / "scripts"):
        for path in source_root.rglob("*.py"):
            for line_number, line in enumerate(path.read_text().splitlines(), start=1):
                if match := NOSEMGREP.search(line):
                    exceptions.append((path, line_number, match.group(1)))

    assert exceptions, "expected narrow compatibility exceptions to remain covered"
    for path, line_number, rule_id in exceptions:
        assert rule_id, f"{path}:{line_number}: bare nosemgrep annotation"
        assert rule_id in rule_ids, (
            f"{path}:{line_number}: nosemgrep rule {rule_id!r} is not in backend/semgrep.yml"
        )


def test_all_repository_nosemgrep_annotations_name_a_rule() -> None:
    for path in (REPOSITORY_ROOT / "Dockerfile",):
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if match := NOSEMGREP.search(line):
                assert match.group(1), f"{path}:{line_number}: bare nosemgrep annotation"
