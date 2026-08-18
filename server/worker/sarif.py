"""Emit normalized findings as SARIF 2.1.0 plus the human summary markdown.

Used by scripts/ci-scan.py for GitHub compute runs. Stdlib only — do not
import server.db / server.api here.
"""
from __future__ import annotations

import hashlib
import os
from collections import Counter
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


SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "UNKNOWN"]

SCANNER_DESCRIPTIONS: dict[str, str] = {
    "semgrep": "static code analysis",
    "gitleaks": "hardcoded secrets",
    "trivy-fs": "dependency CVEs (fs)",
    "trivy-config": "Dockerfile/IaC misconfig",
    "trivy-image": "image CVEs",
    "syft": "SBOM inventory",
    "grype": "dependency CVEs",
    "osv-scanner": "dependency CVEs (OSV)",
}


def summary_markdown(
    findings: list[ParsedFinding],
    status: dict[str, str],
    durations: dict[str, float] | None = None,
) -> str:
    """Per-tool severity matrix + link to the full results artifact."""
    durations = durations or {}
    per_tool: dict[str, Counter[str]] = {}
    for f in findings:
        per_tool.setdefault(f.scanner_kind, Counter())[f.severity] += 1
    # Every scanner that ran gets a row — clean scanners are information too.
    all_tools = sorted(set(per_tool) | set(status))

    lines = ["## assurance-scan", ""]

    lines.append("| Scanner | Checks | CRITICAL | HIGH | MEDIUM | LOW | INFO/UNKNOWN | Total | s |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for tool in all_tools:
        counts = per_tool.get(tool, Counter())
        low_info = counts["LOW"] + counts["INFO"] + counts["UNKNOWN"]
        secs = durations.get(tool)
        lines.append(
            f"| {tool} | {SCANNER_DESCRIPTIONS.get(tool, '·')} "
            f"| {counts['CRITICAL'] or '·'} | {counts['HIGH'] or '·'} "
            f"| {counts['MEDIUM'] or '·'} | {counts['LOW'] or '·'} "
            f"| {low_info or '·'} | {sum(counts.values())} | {secs if secs is not None else '·'} |"
        )
    total = len(findings)
    total_secs = round(sum(durations.values()), 1) if durations else None
    by_sev = Counter(f.severity for f in findings)
    lines.append(
        f"| **Total** |  | **{by_sev['CRITICAL']}** | **{by_sev['HIGH']}** "
        f"| **{by_sev['MEDIUM']}** | **{by_sev['LOW']}** "
        f"| **{by_sev['INFO'] + by_sev['UNKNOWN']}** | **{total}** "
        f"| **{total_secs if total_secs is not None else '·'}** |"
    )
    lines.append("")

    if _on_github():
        lines.append("**Artifacts** (run page → Artifacts section):")
        lines.append("- `assurance-scan-results` — zip containing the full SARIF findings and the CycloneDX SBOM.")
        lines.append("- Docker build record — buildx timing/cache details, debugging only.")
    else:
        lines.append("Full results: SARIF + SBOM files written beside this summary.")
    lines.append("")

    failed = {k: v for k, v in status.items() if v != "ok"}
    if failed:
        lines.append("**Scanners with problems:**")
        for kind, why in sorted(failed.items()):
            lines.append(f"- `{kind}` — {why}")
    return "\n".join(lines) + "\n"


def _on_github() -> bool:
    return bool(os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_RUN_ID"))
