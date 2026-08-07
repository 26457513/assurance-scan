"""v3 test evaluator.

Each test type knows how to evaluate itself from the data the orchestrator
collects (scanner findings, JUnit test case results, manual attestations).

Output: a `TestEvaluation` (pass | fail | pending) plus a detail dict
explaining the decision (e.g., "5 findings at or above HIGH severity").
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any


SEVERITY_RANK: dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "UNKNOWN": 0,
    "INFO": 0,
}


TEST_TYPES = {
    "unit-test",
    "integration-test",
    "e2e-test",
    "scanner-clean",
    "scanner-clean-by-rule",
    "scanner-clean-by-severity",
    "scanner-finds",
    "manual-attestation",
    "imported",
}


@dataclass(frozen=True)
class FindingRecord:
    """Minimal finding shape needed for scanner-test evaluation."""

    scanner_kind: str
    rule_id: str | None
    severity: str
    file_path: str | None


@dataclass(frozen=True)
class TestCaseRecord:
    """Minimal test-case shape needed for unit-test evaluation."""

    __test__ = False  # silence pytest collection warning

    qualified_name: str            # `<classname>::<name>`
    result: str                    # pass | fail | error | skip


@dataclass
class TestEvaluation:
    """Result of evaluating one test spec against collected data."""

    __test__ = False  # silence pytest collection warning

    result: str                    # pass | fail | pending
    detail: dict[str, Any] = field(default_factory=dict)


def evaluate_test(
    spec: dict[str, Any],
    findings: list[FindingRecord],
    test_cases: list[TestCaseRecord],
    manual_attestations: list[dict[str, Any]] | None = None,
) -> TestEvaluation:
    """Evaluate one test against the data the orchestrator collected.

    `findings` is the full list of normalized findings for the run.
    `test_cases` is the full list of JUnit test cases for the run.

    The evaluator filters to what's relevant for this test type.
    """
    test_type = spec.get("type")

    if test_type in ("unit-test", "integration-test", "e2e-test"):
        return _eval_test_suite(spec, test_cases)

    if test_type in ("scanner-clean", "scanner-clean-by-rule", "scanner-clean-by-severity"):
        return _eval_scanner_clean(spec, findings)

    if test_type == "scanner-finds":
        return _eval_scanner_finds(spec, findings)

    if test_type == "manual-attestation":
        return _eval_manual(spec, manual_attestations or [])

    if test_type == "imported":
        return TestEvaluation("pending", {"note": "imported artifacts not yet supported in v3"})

    return TestEvaluation("pending", {"note": f"unknown test type: {test_type}"})


def _eval_test_suite(
    spec: dict[str, Any],
    test_cases: list[TestCaseRecord],
) -> TestEvaluation:
    """Evaluate unit/integration/e2e test specs by name_pattern."""
    pattern = spec.get("name_pattern")
    if not pattern:
        return TestEvaluation("pending", {"note": "no name_pattern supplied"})

    matching = [c for c in test_cases if fnmatch.fnmatchcase(c.qualified_name, pattern)]
    if not matching:
        return TestEvaluation(
            "pending",
            {"note": f"no test cases matched pattern {pattern!r}"},
        )

    failures = [c for c in matching if c.result not in ("pass", "skip")]
    if failures:
        return TestEvaluation(
            "fail",
            {
                "matched_count": len(matching),
                "failed_count": len(failures),
                "failed_names": [c.qualified_name for c in failures[:5]],
            },
        )
    return TestEvaluation(
        "pass",
        {"matched_count": len(matching)},
    )


def _eval_scanner_clean(
    spec: dict[str, Any],
    findings: list[FindingRecord],
) -> TestEvaluation:
    """Evaluate scanner-clean variants."""
    scanner = spec.get("scanner")
    if not scanner:
        return TestEvaluation("pending", {"note": "no scanner supplied"})

    matching = [f for f in findings if f.scanner_kind == scanner]
    if not matching:
        # Scanner didn't run (no findings at all from it) — pending, not pass.
        return TestEvaluation(
            "pending",
            {"note": f"scanner {scanner!r} produced no findings (did it run?)"},
        )

    test_type = spec.get("type")
    if test_type == "scanner-clean":
        failures = matching
    elif test_type == "scanner-clean-by-rule":
        rule_pattern = spec.get("rule_pattern", "")
        try:
            regex = re.compile(rule_pattern)
        except re.error as exc:
            return TestEvaluation("pending", {"note": f"invalid rule_pattern: {exc}"})
        failures = [f for f in matching if f.rule_id and regex.search(f.rule_id)]
    elif test_type == "scanner-clean-by-severity":
        floor = spec.get("severity_floor", "LOW")
        floor_rank = SEVERITY_RANK.get(floor, 0)
        failures = [
            f for f in matching
            if SEVERITY_RANK.get(f.severity, 0) >= floor_rank
        ]
    else:
        return TestEvaluation("pending", {"note": f"unknown scanner-clean variant: {test_type}"})

    if failures:
        return TestEvaluation(
            "fail",
            {
                "scanner": scanner,
                "finding_count": len(failures),
                "sample_rule_ids": list({f.rule_id for f in failures[:5] if f.rule_id}),
                "sample_files": list({f.file_path for f in failures[:5] if f.file_path}),
            },
        )
    return TestEvaluation(
        "pass",
        {
            "scanner": scanner,
            "total_findings": len(matching),
            "note": "scanner ran with zero matching findings",
        },
    )


def _eval_scanner_finds(
    spec: dict[str, Any],
    findings: list[FindingRecord],
) -> TestEvaluation:
    """scanner-finds: scanner must produce ≥1 finding (rare; e.g. SBOM creation)."""
    scanner = spec.get("scanner")
    if not scanner:
        return TestEvaluation("pending", {"note": "no scanner supplied"})
    matching = [f for f in findings if f.scanner_kind == scanner]
    if not matching:
        return TestEvaluation("pending", {"note": f"scanner {scanner!r} produced no findings"})
    return TestEvaluation("pass", {"scanner": scanner, "finding_count": len(matching)})


def _eval_manual(
    spec: dict[str, Any],
    attestations: list[dict[str, Any]],
) -> TestEvaluation:
    """manual-attestation: must have ≥1 attestation record referencing the FR's test id."""
    test_id = spec.get("id", "")
    matching = [a for a in attestations if a.get("test_id") == test_id]
    if not matching:
        return TestEvaluation("pending", {"note": "no attestation on file"})
    return TestEvaluation("pass", {"attestation_count": len(matching)})
