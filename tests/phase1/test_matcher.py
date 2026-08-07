"""v3 test-evaluator tests."""
from __future__ import annotations

from server.state.matcher import (
    FindingRecord,
    TestCaseRecord,
    TestEvaluation,
    evaluate_test,
)


# ---------------------------------------------------------------------------
# unit-test / integration-test / e2e-test
# ---------------------------------------------------------------------------


def test_unit_test_passes_when_pattern_matches_and_all_pass() -> None:
    spec = {"id": "t1", "type": "unit-test", "name_pattern": "tests.foo::*"}
    cases = [
        TestCaseRecord(qualified_name="tests.foo::test_a", result="pass"),
        TestCaseRecord(qualified_name="tests.foo::test_b", result="pass"),
    ]
    ev = evaluate_test(spec, findings=[], test_cases=cases)
    assert ev.result == "pass"
    assert ev.detail["matched_count"] == 2


def test_unit_test_fails_when_any_match_fails() -> None:
    spec = {"id": "t1", "type": "unit-test", "name_pattern": "tests.foo::*"}
    cases = [
        TestCaseRecord(qualified_name="tests.foo::test_a", result="pass"),
        TestCaseRecord(qualified_name="tests.foo::test_b", result="fail"),
    ]
    ev = evaluate_test(spec, findings=[], test_cases=cases)
    assert ev.result == "fail"
    assert ev.detail["failed_count"] == 1


def test_unit_test_pending_when_no_cases_match() -> None:
    spec = {"id": "t1", "type": "unit-test", "name_pattern": "tests.foo::*"}
    cases = [
        TestCaseRecord(qualified_name="tests.other::test_a", result="pass"),
    ]
    ev = evaluate_test(spec, findings=[], test_cases=cases)
    assert ev.result == "pending"


def test_unit_test_skips_are_not_failures() -> None:
    spec = {"id": "t1", "type": "unit-test", "name_pattern": "tests.foo::*"}
    cases = [
        TestCaseRecord(qualified_name="tests.foo::test_a", result="skip"),
    ]
    ev = evaluate_test(spec, findings=[], test_cases=cases)
    assert ev.result == "pass"


# ---------------------------------------------------------------------------
# scanner-clean family
# ---------------------------------------------------------------------------


def test_scanner_clean_passes_when_scanner_produced_zero_findings() -> None:
    spec = {"id": "t1", "type": "scanner-clean", "scanner": "semgrep"}
    # Scanner ran (has at least one finding), but a different scanner.
    findings = [FindingRecord("trivy-fs", "CVE-X", "HIGH", "pkg.json")]
    ev = evaluate_test(spec, findings=findings, test_cases=[])
    assert ev.result == "pending"  # semgrep never ran


def test_scanner_clean_passes_when_scanner_has_findings_but_no_severity_match() -> None:
    spec = {
        "id": "t1",
        "type": "scanner-clean-by-severity",
        "scanner": "semgrep",
        "severity_floor": "HIGH",
    }
    findings = [
        FindingRecord("semgrep", "rule.low1", "LOW", "a.py"),
        FindingRecord("semgrep", "rule.med1", "MEDIUM", "b.py"),
    ]
    ev = evaluate_test(spec, findings=findings, test_cases=[])
    assert ev.result == "pass"


def test_scanner_clean_fails_when_high_severity_present() -> None:
    spec = {
        "id": "t1",
        "type": "scanner-clean-by-severity",
        "scanner": "semgrep",
        "severity_floor": "HIGH",
    }
    findings = [
        FindingRecord("semgrep", "rule.low1", "LOW", "a.py"),
        FindingRecord("semgrep", "rule.high1", "HIGH", "b.py"),
    ]
    ev = evaluate_test(spec, findings=findings, test_cases=[])
    assert ev.result == "fail"
    assert ev.detail["finding_count"] == 1


def test_scanner_clean_by_rule_passes_when_no_rule_matches() -> None:
    spec = {
        "id": "t1",
        "type": "scanner-clean-by-rule",
        "scanner": "trivy-config",
        "rule_pattern": "DS-.*",
    }
    findings = [
        FindingRecord("trivy-config", "CVE-X", "HIGH", "Dockerfile"),
        FindingRecord("trivy-config", "AVD-X", "MEDIUM", "Dockerfile"),
    ]
    ev = evaluate_test(spec, findings=findings, test_cases=[])
    assert ev.result == "pass"


def test_scanner_clean_by_rule_fails_when_rule_matches() -> None:
    spec = {
        "id": "t1",
        "type": "scanner-clean-by-rule",
        "scanner": "trivy-config",
        "rule_pattern": "DS-.*",
    }
    findings = [
        FindingRecord("trivy-config", "DS-0002", "HIGH", "Dockerfile"),
    ]
    ev = evaluate_test(spec, findings=findings, test_cases=[])
    assert ev.result == "fail"
    assert "DS-0002" in ev.detail["sample_rule_ids"]


# ---------------------------------------------------------------------------
# manual-attestation
# ---------------------------------------------------------------------------


def test_manual_attestation_pending_when_no_attestation() -> None:
    spec = {"id": "t1", "type": "manual-attestation"}
    ev = evaluate_test(spec, findings=[], test_cases=[], manual_attestations=[])
    assert ev.result == "pending"


def test_manual_attestation_passes_with_matching_attestation() -> None:
    spec = {"id": "t1", "type": "manual-attestation"}
    attestations = [{"test_id": "t1", "by": "alice"}]
    ev = evaluate_test(spec, findings=[], test_cases=[], manual_attestations=attestations)
    assert ev.result == "pass"


# ---------------------------------------------------------------------------
# scanner-finds
# ---------------------------------------------------------------------------


def test_scanner_finds_passes_when_scanner_has_findings() -> None:
    spec = {"id": "t1", "type": "scanner-finds", "scanner": "syft"}
    findings = [FindingRecord("syft", "package-1", "INFO", None)]
    ev = evaluate_test(spec, findings=findings, test_cases=[])
    assert ev.result == "pass"


def test_scanner_finds_pending_when_scanner_silent() -> None:
    spec = {"id": "t1", "type": "scanner-finds", "scanner": "syft"}
    ev = evaluate_test(spec, findings=[], test_cases=[])
    assert ev.result == "pending"
