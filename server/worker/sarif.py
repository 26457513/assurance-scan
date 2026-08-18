"""Emit normalized findings as a single SARIF 2.1.0 document.

Used by scripts/ci-scan.py for GitHub compute runs. Stdlib only — do not
import server.db / server.api here.
"""
from __future__ import annotations

import hashlib
from typing import Any

from server.worker.parsers.base import ParsedFinding

# our severity -> (SARIF level, numeric security-severity for GitHub filters)
SEVERITY_TO_LEVEL: dict[str, tuple[str, float]] = {
    "CRITICAL": ("error", 9.5),
    "HIGH": ("error", 8.0),
    "MEDIUM": ("warning", 5.0),
    "LOW": ("note", 2.0),
    "INFO": ("note", 2.0),
    "UNKNOWN": ("note", 2.0),
}

SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
    "master/Schemata/sarif-schema-2.1.0.json"
)


def rule_key(f: ParsedFinding) -> str:
    rule_id = f.rule_id or "(unclassified)"
    return f"{f.scanner_kind}/{rule_id}"


def fingerprint(rule_id: str | None, file_path: str | None, line: int | None) -> str:
    """Stable across commits for the same finding at the same location."""
    basis = f"{rule_id or ''}|{file_path or ''}|{line or 0}"
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def build_sarif(findings: list[ParsedFinding]) -> dict[str, Any]:
    """One tool, one run, rules deduped by scanner/rule_id."""
    keys: list[str] = []
    for f in findings:
        key = rule_key(f)
        if key not in keys:
            keys.append(key)
    rule_index = {k: i for i, k in enumerate(keys)}

    rules = []
    for key in keys:
        # Any finding with this key gives the severity; first wins.
        sample = next(f for f in findings if rule_key(f) == key)
        level, security_severity = SEVERITY_TO_LEVEL.get(sample.severity, ("note", 2.0))
        rules.append({
            "id": key,
            "shortDescription": {"text": sample.rule_id or sample.scanner_kind},
            "defaultConfiguration": {"level": level},
            "properties": {
                "tags": [sample.scanner_kind],
                "security-severity": str(security_severity),
            },
        })

    results = []
    for f in findings:
        level, _ = SEVERITY_TO_LEVEL.get(f.severity, ("note", 2.0))
        result: dict[str, Any] = {
            "ruleId": rule_key(f),
            "ruleIndex": rule_index[rule_key(f)],
            "level": level,
            "message": {"text": f.message},
            "partialFingerprints": {
                "primaryLocationLineHash": fingerprint(f.rule_id, f.file_path, f.line_start),
            },
            "properties": {
                "scanner": f.scanner_kind,
                "severity": f.severity,
                "theme": f.theme,
                "compliance_tags": list(f.compliance_tags),
            },
        }
        if f.file_path:
            physical: dict[str, Any] = {
                "artifactLocation": {"uri": f.file_path, "uriBaseId": "%SRCROOT%"},
            }
            if f.line_start is not None:
                region: dict[str, int] = {"startLine": f.line_start}
                if f.line_end is not None:
                    region["endLine"] = f.line_end
                physical["region"] = region
            result["locations"] = [{"physicalLocation": physical}]
        results.append(result)

    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "assurance-scan",
                    "informationUri": "https://github.com/26457513/assurance-scan",
                    "rules": rules,
                },
            },
            "results": results,
        }],
    }
