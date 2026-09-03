"""Parse Gitleaks JSON output into normalized findings.

Gitleaks emits a flat array of leak records. Each has RuleID, File,
StartLine, Description, Secret, and Rule. Secret material is never copied into
the normalized finding, even when Gitleaks was invoked without redaction.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.modules.atomic.scanning.finding_parser.models import (
    FindingParser,
    ParsedFinding,
    normalize_line_range,
    strip_mount_prefix,
)


SEVERITY_RULE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(aws|gcp|azure|stripe|github|gitlab|slack|jwt|private[_-]?key)\b", re.I), "HIGH"),
    (re.compile(r"\b(password|passwd|pwd|token|secret|api[_-]?key)\b", re.I), "MEDIUM"),
)


def _severity_for_rule(rule_id: str) -> str:
    for pattern, sev in SEVERITY_RULE_PATTERNS:
        if pattern.search(rule_id):
            return sev
    return "MEDIUM"


class GitleaksJsonParser(FindingParser):
    """Parses Gitleaks JSON stdout into findings."""

    def parse(self, raw: bytes) -> list[ParsedFinding]:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserError(f"invalid gitleaks JSON: {exc}") from exc

        if not isinstance(doc, list):
            return []

        findings: list[ParsedFinding] = []
        for item in doc:
            parsed = self._parse_item(item)
            if parsed is not None:
                findings.append(parsed)
        return findings

    def _parse_item(self, item: dict[str, Any]) -> ParsedFinding | None:
        rule_id = item.get("RuleID") or item.get("rule", {}).get("id")
        if not rule_id:
            return None

        file_path = strip_mount_prefix(item.get("File") or item.get("file"))
        line_start, line_end = normalize_line_range(
            item.get("StartLine") or item.get("startLine"),
            item.get("EndLine") or item.get("endLine"),
        )

        message = (
            item.get("Description")
            or item.get("Description")
            or f"leak detected by rule {rule_id}"
        )
        return ParsedFinding(
            scanner_kind="gitleaks",
            rule_id=rule_id,
            severity=_severity_for_rule(rule_id),
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            message=message,
            theme="secrets",
            fix_strategy="single-file",
            compliance_tags=(),
        )


class ParserError(Exception):
    """Raised when scanner output can't be parsed."""
