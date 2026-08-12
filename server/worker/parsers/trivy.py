"""Parse Trivy JSON output (works for both `fs` and `config` modes).

Trivy emits an object with `Results` -> list of {Target, MisconfSummary,
Vulnerabilities}. Each vulnerability has VulnerabilityID, PkgName,
InstalledVersion, FixedVersion, Severity, Title, Description.
"""
from __future__ import annotations

import json
from typing import Any

from server.worker.parsers.base import FindingParser, ParsedFinding


SEVERITY_MAP: dict[str, str] = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "UNKNOWN": "UNKNOWN",
}


class TrivyJsonParser(FindingParser):
    """Parses Trivy JSON stdout into findings.

    Set `mode='vuln'` for `trivy fs` output (vulnerability findings) or
    `mode='config'` for `trivy config` output (misconfigurations).
    """

    def __init__(self, scanner_kind: str, mode: str = "vuln") -> None:
        self.scanner_kind = scanner_kind
        self.mode = mode

    def parse(self, raw: bytes) -> list[ParsedFinding]:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserError(f"invalid trivy JSON: {exc}") from exc

        results = doc.get("Results") or []
        findings: list[ParsedFinding] = []

        for result in results:
            target = result.get("Target")
            if self.mode == "vuln":
                for vuln in result.get("Vulnerabilities") or []:
                    parsed = self._parse_vuln(vuln, target)
                    if parsed is not None:
                        findings.append(parsed)
            else:  # config / misconfigurations
                for misconf in result.get("Misconfigurations") or []:
                    parsed = self._parse_misconf(misconf, target)
                    if parsed is not None:
                        findings.append(parsed)

        return findings

    def _parse_vuln(self, v: dict[str, Any], target: str | None) -> ParsedFinding | None:
        vid = v.get("VulnerabilityID")
        if not vid:
            return None
        severity = SEVERITY_MAP.get((v.get("Severity") or "UNKNOWN").upper(), "UNKNOWN")
        installed = v.get("InstalledVersion")
        fixed = v.get("FixedVersion")
        pkg = v.get("PkgName") or "<pkg>"
        title = v.get("Title") or v.get("Description") or vid
        message = f"{pkg} {installed} vulnerable to {vid}"
        if fixed:
            message += f" (fixed in {fixed})"
        message += f": {(v.get('Description') or title)[:300]}"

        return ParsedFinding(
            scanner_kind=self.scanner_kind,
            rule_id=vid,
            severity=severity,
            file_path=target,
            line_start=None,
            line_end=None,
            message=message,
            theme="dependency",
            fix_strategy="dependency-update" if fixed else "config-only",
            compliance_tags=tuple(v.get("CweIDs") or []),
        )

    def _parse_misconf(self, m: dict[str, Any], target: str | None) -> ParsedFinding | None:
        mid = m.get("ID")
        if not mid:
            return None
        severity = SEVERITY_MAP.get((m.get("Severity") or "UNKNOWN").upper(), "UNKNOWN")
        title = m.get("Title") or mid
        message = m.get("Description") or title
        resolution = m.get("Resolution")
        if resolution:
            message = f"{message} Resolution: {resolution}"

        return ParsedFinding(
            scanner_kind=self.scanner_kind,
            rule_id=mid,
            severity=severity,
            file_path=target,
            line_start=None,
            line_end=None,
            message=message,
            theme="misconfiguration",
            fix_strategy="config-only",
            compliance_tags=(),
        )


class ParserError(Exception):
    """Raised when scanner output can't be parsed."""
