"""Pure SARIF, summary, and CI payload rendering."""
from __future__ import annotations

import hashlib
import os
import urllib.parse
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.modules.shared.contracts.findings import PACKAGE_IDENTITY_CAPABILITY

from .models import Finding

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


def rule_key(finding: Finding) -> str:
    rule_id = finding.rule_id or "(unclassified)"
    return f"{finding.scanner_kind}/{rule_id}"


def fingerprint(rule_id: str | None, file_path: str | None, line: int | None) -> str:
    """Return a stable location fingerprint for a finding."""
    basis = f"{rule_id or ''}|{file_path or ''}|{line or 0}"
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def build_sarif(findings: Sequence[Finding]) -> dict[str, Any]:
    """Build one SARIF tool run with rules deduplicated by scanner and rule."""
    keys: list[str] = []
    for finding in findings:
        key = rule_key(finding)
        if key not in keys:
            keys.append(key)
    rule_index = {key: index for index, key in enumerate(keys)}

    rules = []
    for key in keys:
        sample = next(finding for finding in findings if rule_key(finding) == key)
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
    for finding in findings:
        level, _ = SEVERITY_TO_LEVEL.get(finding.severity, ("note", 2.0))
        result: dict[str, Any] = {
            "ruleId": rule_key(finding),
            "ruleIndex": rule_index[rule_key(finding)],
            "level": level,
            "message": {"text": finding.message},
            "partialFingerprints": {
                "primaryLocationLineHash": fingerprint(
                    finding.rule_id, finding.file_path, finding.line_start
                ),
            },
            "properties": {
                "scanner": finding.scanner_kind,
                "severity": finding.severity,
                "theme": finding.theme,
                "compliance_tags": list(finding.compliance_tags),
            },
        }
        if finding.file_path:
            physical: dict[str, Any] = {
                "artifactLocation": {"uri": finding.file_path, "uriBaseId": "%SRCROOT%"},
            }
            if finding.line_start is not None:
                region: dict[str, int] = {"startLine": finding.line_start}
                if finding.line_end is not None:
                    region["endLine"] = finding.line_end
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


def md_escape(text: str | None) -> str:
    """Neutralize markdown and HTML in scanner-derived text."""
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("`", "\\`")
    )


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
    findings: Sequence[Finding],
    status: dict[str, str],
    durations: dict[str, float] | None = None,
) -> str:
    """Render the existing per-tool severity matrix and result link."""
    durations = durations or {}
    per_tool: dict[str, Counter[str]] = {}
    for finding in findings:
        per_tool.setdefault(finding.scanner_kind, Counter())[finding.severity] += 1
    all_tools = sorted(set(per_tool) | set(status))

    lines = ["## assurance-scan", ""]
    lines.append("| Scanner | Checks | CRITICAL | HIGH | MEDIUM | LOW | INFO/UNKNOWN | Total | s |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for tool in all_tools:
        counts = per_tool.get(tool, Counter())
        low_info = counts["LOW"] + counts["INFO"] + counts["UNKNOWN"]
        seconds = durations.get(tool)
        lines.append(
            f"| {md_escape(tool)} | {SCANNER_DESCRIPTIONS.get(tool, '·')} "
            f"| {counts['CRITICAL'] or '·'} | {counts['HIGH'] or '·'} "
            f"| {counts['MEDIUM'] or '·'} | {counts['LOW'] or '·'} "
            f"| {low_info or '·'} | {sum(counts.values())} | {seconds if seconds is not None else '·'} |"
        )
    total = len(findings)
    total_seconds = round(sum(durations.values()), 1) if durations else None
    by_severity = Counter(finding.severity for finding in findings)
    lines.append(
        f"| **Total** |  | **{by_severity['CRITICAL']}** | **{by_severity['HIGH']}** "
        f"| **{by_severity['MEDIUM']}** | **{by_severity['LOW']}** "
        f"| **{by_severity['INFO'] + by_severity['UNKNOWN']}** | **{total}** "
        f"| **{total_seconds if total_seconds is not None else '·'}** |"
    )
    lines.append("")

    if _on_github():
        ui_base = os.environ.get("ASSURANCE_SCAN_URL", "").rstrip("/")
        repo = os.environ.get("ASSURANCE_SCAN_REPO") or os.environ.get("GITHUB_REPOSITORY")
        run_id = os.environ.get("GITHUB_RUN_ID")
        if ui_base and repo and run_id:
            slug = urllib.parse.quote(f"github:{repo}", safe="")
            lines.append(
                f'<a href="{ui_base}/projects/{slug}?run=gh-{run_id}" '
                'target="_blank">Detailed Scan Results</a>'
            )
    else:
        lines.append("Full results: SARIF + SBOM files written beside this summary.")
    lines.append("")

    failed = {kind: reason for kind, reason in status.items() if reason != "ok"}
    if failed:
        lines.append("**Scanners with problems:**")
        for kind, reason in sorted(failed.items()):
            lines.append(f"- `{md_escape(kind)}` — {md_escape(reason)}")
    return "\n".join(lines) + "\n"


def _on_github() -> bool:
    return bool(os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_RUN_ID"))


def github_run_url() -> str | None:
    server = os.environ.get("GITHUB_SERVER_URL")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


def github_branch(environ: Mapping[str, str] | None = None) -> str | None:
    """Return the source branch for PRs and the ref branch for other runs."""
    values = os.environ if environ is None else environ
    return values.get("GITHUB_HEAD_REF") or values.get("GITHUB_REF_NAME")


def ci_payload(
    findings: Sequence[Finding],
    status: dict[str, str],
    durations: dict[str, float],
    repo: str | None,
    run_url: str | None,
    github_run_id: str | None = None,
    branch: str | None = None,
    commit: str | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    """Render the existing version-one GitHub Actions findings payload."""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "capabilities": [PACKAGE_IDENTITY_CAPABILITY],
        "source": "github-actions",
        "repo": repo,
        "github_run_id": github_run_id,
        "run_url": run_url,
        "branch": branch,
        "commit": commit,
        "scanner_status": status,
        "durations": durations,
        "summary": {
            "total": len(findings),
            "by_severity": dict(Counter(finding.severity for finding in findings)),
            "by_scanner": dict(Counter(finding.scanner_kind for finding in findings)),
        },
        "findings": [
            {
                "id": f"F-{index + 1:03d}",
                "scanner": finding.scanner_kind,
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "file_path": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
                "message": finding.message,
                "theme": finding.theme,
                "fix_strategy": finding.fix_strategy,
                "compliance_tags": list(finding.compliance_tags),
                "package_name": finding.package_name,
                "package_version": finding.package_version,
                "package_ecosystem": finding.package_ecosystem,
                "package_purl": finding.package_purl,
            }
            for index, finding in enumerate(findings)
        ],
    }
    if source_root is not None:
        from app.modules.atomic.ingestion.source_context import extract_source_contexts

        extracted = extract_source_contexts(
            source_root,
            payload["findings"],
            schema_version=1,
        )
        payload["findings"] = list(extracted.findings)
        payload["source_contexts"] = list(extracted.contexts)
    return payload
