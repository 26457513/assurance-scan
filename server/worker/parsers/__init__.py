"""Per-scanner output parsers.

Each parser turns raw scanner output (SARIF, JSON, etc.) into a list of
finding dicts suitable for `FindingRepository.bulk_insert`.

Common contract: input is the raw bytes the scanner wrote to stdout;
output is a list of `ParsedFinding` dataclasses.
"""
from __future__ import annotations

from server.worker.parsers.base import FindingParser, ParsedFinding
from server.worker.parsers import (
    gitleaks,
    grype,
    osv_scanner,
    semgrep,
    syft,
    trivy,
)
from server.worker.scanners import ScannerConfig


def parser_for(scanner: ScannerConfig) -> FindingParser:
    """Return the parser instance for a given scanner config."""
    if scanner.kind == "semgrep":
        return semgrep.SemgrepSarifParser()
    if scanner.kind == "gitleaks":
        return gitleaks.GitleaksJsonParser()
    if scanner.kind == "trivy-fs":
        return trivy.TrivyJsonParser(scanner_kind="trivy-fs", mode="vuln")
    if scanner.kind == "trivy-config":
        return trivy.TrivyJsonParser(scanner_kind="trivy-config", mode="config")
    if scanner.kind == "syft":
        return syft.SyftSbomParser()
    if scanner.kind == "grype":
        return grype.GrypeJsonParser()
    if scanner.kind == "osv-scanner":
        return osv_scanner.OsvScannerJsonParser()
    raise ValueError(f"no parser registered for scanner kind: {scanner.kind}")


__all__ = ["FindingParser", "ParsedFinding", "parser_for"]
