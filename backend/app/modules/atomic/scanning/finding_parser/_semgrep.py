"""Parse Semgrep SARIF output into normalized findings.

Semgrep emits SARIF v2.1.0. We extract rule metadata (severity, id) from
`tool.driver.rules` and per-result details (path, line, message) from
`results`.
"""
from __future__ import annotations

import json
from typing import Any

from app.modules.atomic.scanning.finding_parser.models import FindingParser, ParsedFinding


# SARIF level -> our severity. Semgrep maps its own severity to SARIF levels;
# we keep rule metadata `security-severity` if present for finer-grained CVSS.
SARIF_LEVEL_TO_SEVERITY: dict[str, str] = {
    "error": "HIGH",
    "warning": "MEDIUM",
    "note": "LOW",
    "none": "INFO",
}


def _normalize_severity(level: str | None, properties: dict[str, Any]) -> str:
    """Prefer the explicit Semgrep severity if present."""
    sev = properties.get("security-severity")
    if isinstance(sev, (int, float)):
        if sev >= 9.0:
            return "CRITICAL"
        if sev >= 7.0:
            return "HIGH"
        if sev >= 4.0:
            return "MEDIUM"
        return "LOW"
    if level:
        return SARIF_LEVEL_TO_SEVERITY.get(level, "UNKNOWN")
    return "UNKNOWN"


def _strip_prefix(path: str, project_root: str) -> str:
    """Make a path repo-relative. Falls back to the input untouched."""
    if path.startswith(project_root):
        return path[len(project_root):].lstrip("/")
    return path


class SemgrepSarifParser(FindingParser):
    """Parses Semgrep SARIF stdout into findings."""

    def __init__(self, project_root: str = "") -> None:
        # Semgrep emits absolute paths inside the container. Strip project
        # root so we store repo-relative paths.
        self.project_root = project_root.rstrip("/") or "/src"

    def parse(self, raw: bytes) -> list[ParsedFinding]:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserError(f"invalid SARIF JSON: {exc}") from exc

        runs = doc.get("runs", [])
        if not runs:
            return []

        findings: list[ParsedFinding] = []
        for run in runs:
            rules_by_id = self._index_rules(run)
            results = run.get("results", []) or []
            for result in results:
                # Honour SARIF suppressions — semgrep emits a `suppressions` array
                # on results muted by inline suppression annotations. Skip them so
                # inline ignores are reflected in the findings count and FR state.
                if result.get("suppressions"):
                    continue
                parsed = self._parse_result(result, rules_by_id)
                if parsed is not None:
                    findings.append(parsed)
        return findings

    def _index_rules(self, run: dict[str, Any]) -> dict[str, dict[str, Any]]:
        driver = (
            run.get("tool", {}).get("driver", {}) or {}
        )
        rules = driver.get("rules", []) or []
        return {rule.get("id"): rule for rule in rules if rule.get("id")}

    def _parse_result(
        self,
        result: dict[str, Any],
        rules_by_id: dict[str, dict[str, Any]],
    ) -> ParsedFinding | None:
        raw_rule_id = result.get("ruleId")
        rule_id = raw_rule_id if isinstance(raw_rule_id, str) else None
        rule = rules_by_id.get(rule_id, {}) if rule_id is not None else {}
        properties = rule.get("properties", {}) or {}

        level = result.get("level") or rule.get("defaultConfiguration", {}).get("level")
        severity = _normalize_severity(level, properties)

        locations = result.get("locations") or []
        if not locations:
            return None
        phys = locations[0].get("physicalLocation", {}) or {}
        artifact = phys.get("artifactLocation", {}) or {}
        region = phys.get("region", {}) or {}

        file_path = artifact.get("uri")
        if file_path:
            file_path = _strip_prefix(file_path, self.project_root)

        message = (
            result.get("message", {}).get("text")
            or properties.get("message")
            or rule.get("shortDescription", {}).get("text")
            or rule_id
            or "(no message)"
        )

        return ParsedFinding(
            scanner_kind="semgrep",
            rule_id=rule_id,
            severity=severity,
            file_path=file_path,
            line_start=region.get("startLine"),
            line_end=region.get("endLine"),
            message=message,
            theme=properties.get("tags", [None])[0] if properties.get("tags") else None,
            compliance_tags=tuple(properties.get("tags", [])),
        )


class ParserError(Exception):
    """Raised when scanner output can't be parsed."""
