"""Parse osv-scanner JSON output into normalized findings.

osv-scanner emits {results: [{source, packages: [{package, vulnerabilities: [...]}]}]}.
Each (package, vulnerability) pair is one finding.
"""
from __future__ import annotations

import json
from typing import Any

from app.modules.atomic.scanning.finding_parser.models import (
    FindingParser,
    ParsedFinding,
    bounded_text,
    strip_mount_prefix,
)


SEVERITY_MAP: dict[str, str] = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MODERATE": "MEDIUM",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
}


def _severity_for(vuln: dict[str, Any]) -> str:
    """osv.dev uses CVSS or database_specific severity strings."""
    for key in ("CVSS_V3", "CVSS_V4"):
        cvss = vuln.get("severity", {}).get(key) if isinstance(vuln.get("severity"), dict) else None
        if isinstance(cvss, str) and "CVSS" in cvss:
            score = _extract_cvss_score(cvss)
            if score is not None:
                if score >= 9.0:
                    return "CRITICAL"
                if score >= 7.0:
                    return "HIGH"
                if score >= 4.0:
                    return "MEDIUM"
                return "LOW"
    sev = vuln.get("database_specific", {}).get("severity")
    if isinstance(sev, str):
        return SEVERITY_MAP.get(sev.upper(), "UNKNOWN")
    return "UNKNOWN"


def _extract_cvss_score(vector: str) -> float | None:
    """Pull the numeric score out of a CVSS vector string."""
    # CVSS:3.1/AV:N/AC:L/... — score not in vector; rely on suffix if present.
    if "CVSS" in vector:
        # Sometimes osv gives us "CVSS_V3: 7.5" format
        import re
        match = re.search(r"(\d+\.\d+)", vector)
        if match:
            return float(match.group(1))
    return None


class OsvScannerJsonParser(FindingParser):
    """Parses osv-scanner JSON stdout into findings."""

    def parse(self, raw: bytes) -> list[ParsedFinding]:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserError(f"invalid osv-scanner JSON: {exc}") from exc

        results = doc.get("results") or []
        findings: list[ParsedFinding] = []

        for result in results:
            source = result.get("source", {}).get("path") or result.get("source", {}).get("location")
            for pkg_info in result.get("packages") or []:
                pkg = pkg_info.get("package", {}) or {}
                pkg_name = pkg.get("name") or "<pkg>"
                pkg_version = pkg.get("version")

                for vuln in pkg_info.get("vulnerabilities") or []:
                    vid = vuln.get("id")
                    if not vid:
                        continue
                    aliases = vuln.get("aliases") or []
                    rule_id = vid if not aliases else f"{vid} ({', '.join(aliases[:2])})"

                    severity = _severity_for(vuln)
                    fixed = vuln.get("affected", [{}])[0].get("ranges", [{}])[0].get("events", [])
                    fixed_versions = [
                        fixed_version
                        for event in fixed
                        if isinstance(event, dict)
                        and isinstance((fixed_version := event.get("fixed")), str)
                    ]
                    summary = vuln.get("summary") or vid

                    message = f"{pkg_name} {pkg_version} vulnerable to {vid}"
                    if fixed_versions:
                        message += f" (fixed in {', '.join(fixed_versions)})"
                    message += f": {summary[:300]}"

                    findings.append(ParsedFinding(
                        scanner_kind="osv-scanner",
                        rule_id=rule_id,
                        severity=severity,
                        file_path=strip_mount_prefix(source),
                        line_start=None,
                        line_end=None,
                        message=message,
                        theme="dependency",
                        fix_strategy="dependency-update" if fixed_versions else "config-only",
                        compliance_tags=(),
                        package_name=bounded_text(pkg.get("name"), 512),
                        package_version=bounded_text(pkg.get("version"), 256),
                        package_ecosystem=bounded_text(pkg.get("ecosystem"), 64),
                        package_purl=bounded_text(pkg.get("purl"), 1024),
                    ))

        return findings


class ParserError(Exception):
    """Raised when scanner output can't be parsed."""
