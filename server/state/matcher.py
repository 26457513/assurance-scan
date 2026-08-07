"""Evidence-to-spec matching algorithm (plan §4).

A spec defines what counts as evidence for an FR. Matching checks
whether an evidence record satisfies a given spec.

Test name format conventions:
  - pytest: `<rel_path>::<ClassName>::<method_name>`
  - jest:    `<rel_path>::<test_name>`
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any


TEST_TYPES = {"unit-test", "integration-test", "e2e-test"}


class ConflictError(Exception):
    """Raised when evidence collection itself can't decide a result.

    Currently unused but kept as a placeholder for future validation logic.
    """


@dataclass(frozen=True)
class EvidenceRecord:
    """Minimal shape of an evidence row needed for matching."""

    type: str
    source: dict[str, Any]
    result: str                    # 'pass' | 'fail' | 'info' | 'manual'


def matches_spec(spec: dict[str, Any], evidence: EvidenceRecord) -> bool:
    """True if evidence matches the spec's source criteria."""
    if evidence.type != spec.get("type"):
        return False

    if evidence.type == "scanner-result":
        return (
            evidence.source.get("kind") == spec.get("source_kind")
            and evidence.source.get("rule_id") == spec.get("rule_id")
        )

    if evidence.type in TEST_TYPES:
        pattern = spec.get("name_pattern")
        if not pattern:
            return False
        test_name = evidence.source.get("test_name", "")
        return fnmatch.fnmatchcase(test_name, pattern)

    if evidence.type == "manual-attestation":
        return True

    if evidence.type == "imported":
        return evidence.source.get("format") == spec.get("format")

    if evidence.type == "generated":
        return evidence.source.get("name_pattern") == spec.get("name_pattern")

    if evidence.type == "proof-bundle":
        return True

    return False


def spec_matches_count(
    spec: dict[str, Any],
    evidence_records: list[EvidenceRecord],
) -> tuple[int, bool]:
    """Count matching evidence records for a spec.

    Returns (count, has_failing_result). A spec with at least one matching
    record with `result='fail'` while `expected_result='pass'` is a conflict.
    """
    matches = [e for e in evidence_records if matches_spec(spec, e)]
    expected = spec.get("expected_result", "pass")
    has_fail = any(
        e.result == "fail" and expected == "pass" for e in matches
    )
    satisfied = any(
        e.result == expected for e in matches
    )
    return (len(matches), has_fail), satisfied


def spec_identity(spec: dict[str, Any]) -> str:
    """Stable string identity for a spec, used for deduping and reporting."""
    parts = [str(spec.get("type", ""))]
    for k in ("source_kind", "rule_id", "name_pattern", "format", "expected_result"):
        parts.append(f"{k}={spec.get(k, '')}")
    return "|".join(parts)
