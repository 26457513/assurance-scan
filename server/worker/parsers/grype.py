"""Parse Grype JSON output into normalized findings.

Grype emits {matches: [{vulnerability: {...}, artifact: {...}}]}.
Each match is one finding.
"""
from __future__ import annotations

import json
from typing import Any

from server.worker.parsers.base import FindingParser, ParsedFinding


SEVERITY_MAP: dict[str, str] = {
    "Critical": "CRITICAL",
    "High": "HIGH",
    "Medium": "MEDIUM",
    "Low": "LOW",
    "Negligible": "LOW",
    "Unknown": "UNKNOWN",
}


class GrypeJsonParser(FindingParser):
    """Parses Grype JSON stdout into findings."""

    def parse(self, raw: bytes) -> list[ParsedFinding]:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserError(f"invalid grype JSON: {exc}") from exc

        matches = doc.get("matches") or []
        findings: list[ParsedFinding] = []

        for index, m in enumerate(matches):
            parsed = self._parse_match(m, index)
            if parsed is not None:
                findings.append(parsed)
        return findings

    def _parse_match(self, m: dict[str, Any], index: int) -> ParsedFinding | None:
        vuln = m.get("vulnerability", {}) or {}
        artifact = m.get("artifact", {}) or {}

        vid = vuln.get("id")
        if not vid:
            return None

        severity = SEVERITY_MAP.get(vuln.get("severity", "Unknown"), "UNKNOWN")
        pkg = artifact.get("name") or "<pkg>"
        version = artifact.get("version")
        fixed_versions = vuln.get("fix", {}).get("versions") or []
        description = vuln.get("description") or vid

        message = f"{pkg} {version} vulnerable to {vid}"
        if fixed_versions:
            message += f" (fixed in {', '.join(map(str, fixed_versions))})"
        message += f": {description[:300]}"

        return ParsedFinding(
            scanner_kind="grype",
            rule_id=vid,
            severity=severity,
            file_path=artifact.get("locations", [{}])[0].get("path") if artifact.get("locations") else None,
            line_start=None,
            line_end=None,
            message=message,
            theme="dependency",
            fix_strategy="dependency-update" if fixed_versions else "config-only",
            compliance_tags=(),
            raw_index=index,
        )


class ParserError(Exception):
    """Raised when scanner output can't be parsed."""
