"""Public API for scanner result documents."""

from .service import (
    SARIF_SCHEMA,
    SCANNER_DESCRIPTIONS,
    SEVERITY_ORDER,
    SEVERITY_TO_LEVEL,
    build_sarif,
    ci_payload,
    fingerprint,
    github_branch,
    github_run_url,
    md_escape,
    rule_key,
    summary_markdown,
)

__all__ = [
    "SARIF_SCHEMA",
    "SCANNER_DESCRIPTIONS",
    "SEVERITY_ORDER",
    "SEVERITY_TO_LEVEL",
    "build_sarif",
    "ci_payload",
    "fingerprint",
    "github_branch",
    "github_run_url",
    "md_escape",
    "rule_key",
    "summary_markdown",
]
