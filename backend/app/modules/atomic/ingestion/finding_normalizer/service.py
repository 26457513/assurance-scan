"""Deterministic conversion from bundle findings to repository rows."""
from __future__ import annotations

from collections.abc import Iterable

from app.modules.shared.contracts.findings import FindingPayload, NormalizedFinding


def normalize_findings(
    run_id: str,
    findings: Iterable[FindingPayload],
) -> list[NormalizedFinding]:
    """Normalize findings exactly as the legacy CI ingestion path did."""

    return [
        {
            "run_id": run_id,
            **(
                {"finding_key": finding["finding_key"]}
                if finding.get("finding_key") is not None
                else {}
            ),
            "scanner_kind": finding["scanner"],
            "rule_id": finding.get("rule_id"),
            "severity": finding.get("severity"),
            "file_path": finding.get("file_path"),
            "line_start": finding.get("line_start"),
            "line_end": finding.get("line_end"),
            "message": finding.get("message") or "",
            "theme": finding.get("theme"),
            "fix_strategy": finding.get("fix_strategy"),
            "compliance_tags": finding.get("compliance_tags") or [],
        }
        for finding in findings
    ]
