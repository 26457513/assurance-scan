"""Tests for the SARIF emitter used by CI scans."""
from __future__ import annotations

from server.worker.parsers.base import ParsedFinding
from server.worker.sarif import build_sarif, fingerprint


def _finding(**overrides) -> ParsedFinding:
    defaults = dict(
        scanner_kind="semgrep",
        rule_id="rule-a",
        severity="HIGH",
        file_path="src/app.py",
        line_start=10,
        line_end=10,
        message="Detected eval()",
    )
    defaults.update(overrides)
    return ParsedFinding(**defaults)


def test_severity_maps_to_sarif_levels_and_rules_dedupe() -> None:
    findings = [
        _finding(),
        _finding(severity="CRITICAL", line_start=20),  # same rule key, different result
        _finding(rule_id="rule-b", severity="MEDIUM"),
        _finding(scanner_kind="gitleaks", rule_id=None, severity="LOW"),
    ]
    doc = build_sarif(findings)
    run = doc["runs"][0]
    rules = run["tool"]["driver"]["rules"]
    assert [r["id"] for r in rules] == ["semgrep/rule-a", "semgrep/rule-b", "gitleaks/(unclassified)"]

    by_rule = {r["id"]: r for r in rules}
    assert by_rule["semgrep/rule-a"]["defaultConfiguration"]["level"] == "error"
    assert by_rule["semgrep/rule-b"]["defaultConfiguration"]["level"] == "warning"
    assert by_rule["gitleaks/(unclassified)"]["defaultConfiguration"]["level"] == "note"

    results = run["results"]
    assert len(results) == 4
    assert results[0]["level"] == "error"
    assert results[1]["level"] == "error"
    assert results[2]["level"] == "warning"
    # ruleIndex points at the matching entry in the rules array
    assert results[2]["ruleIndex"] == 1


def test_result_location_and_fingerprint() -> None:
    doc = build_sarif([_finding()])
    result = doc["runs"][0]["results"][0]
    phys = result["locations"][0]["physicalLocation"]
    assert phys["artifactLocation"]["uri"] == "src/app.py"
    assert phys["region"] == {"startLine": 10, "endLine": 10}
    assert result["partialFingerprints"]["primaryLocationLineHash"] == fingerprint(
        "rule-a", "src/app.py", 10
    )
    # Same finding on another line gets a different fingerprint.
    other = build_sarif([_finding(line_start=11)])["runs"][0]["results"][0]
    assert other["partialFingerprints"]["primaryLocationLineHash"] != result["partialFingerprints"]["primaryLocationLineHash"]


def test_findings_without_location_omit_locations() -> None:
    doc = build_sarif([_finding(file_path=None, line_start=None, line_end=None)])
    result = doc["runs"][0]["results"][0]
    assert "locations" not in result
    assert result["partialFingerprints"]["primaryLocationLineHash"] == fingerprint("rule-a", None, None)
