"""Select a normalized finding parser for a scanner configuration."""

from app.modules.atomic.scanning.scanner_catalog import ScannerConfig

from ._gitleaks import GitleaksJsonParser
from ._grype import GrypeJsonParser
from ._osv_scanner import OsvScannerJsonParser
from ._semgrep import SemgrepSarifParser
from ._syft import SyftSbomParser
from ._trivy import TrivyJsonParser
from .models import FindingParser


def parser_for(scanner: ScannerConfig) -> FindingParser:
    """Return the parser implementation for ``scanner``."""
    parsers: dict[str, type[FindingParser]] = {
        "semgrep": SemgrepSarifParser,
        "gitleaks": GitleaksJsonParser,
        "syft": SyftSbomParser,
        "grype": GrypeJsonParser,
        "osv-scanner": OsvScannerJsonParser,
    }
    if scanner.kind in {"trivy-fs", "trivy-image"}:
        return TrivyJsonParser(scanner_kind=scanner.kind, mode="vuln")
    if scanner.kind == "trivy-config":
        return TrivyJsonParser(scanner_kind="trivy-config", mode="config")
    parser_type = parsers.get(scanner.kind)
    if parser_type is None:
        raise ValueError(f"no parser registered for scanner kind: {scanner.kind}")
    return parser_type()


__all__ = ["parser_for"]
