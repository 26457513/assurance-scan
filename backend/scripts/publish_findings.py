#!/usr/bin/env python3
"""Publish a single agent-friendly findings.json into the user's actual repo.

After a scan, the wrapper invokes this script to:
  1. Read raw scanner outputs (semgrep SARIF, gitleaks JSON, trivy config JSON).
  2. Read evidence-manifest.json (for git context) and graph-manifest.json
     (for compliance join).
  3. Normalise findings to one row per finding, with repo-relative paths,
     fix strategy classification, theme grouping, and compliance tags.
  4. Decide pr_strategy: single if distinct files <= threshold, else themed.
  5. Write findings.json + a stable findings.latest.json pointer.
  6. Copy raw reports for forensic access.
  7. Ensure the publish dir is gitignored in the user's repo.
  8. Optionally install the /fix-assurance-findings agent skill on first run.

Pure helpers (build_findings_json, classify_fix_strategy, theme_for,
remap_snapshot_path) are importable for unit tests.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from scanner_parsers import load_json, remap_snapshot_path
except ImportError:
    # Allow running as a standalone script from anywhere
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scanner_parsers import load_json, remap_snapshot_path  # type: ignore


PR_STRATEGY_SINGLE_FILE_THRESHOLD = 15

PUBLISH_DIRNAME = "reports"
LATEST_POINTER_NAME = "findings.latest.json"

AGENT_SKILL_REL_PATH = Path("resources") / "assets" / "agent-skill" / "fix-assurance-findings.md"
AGENT_SKILL_INSTALL_REL_PATH = Path(".claude") / "commands" / "fix-assurance-findings.md"

SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}

GITIGNORE_MARKER = ".assurance-scan/reports/"
GITIGNORE_BLOCK = (
    "\n# assurance-scan local reports (do not commit)\n"
    ".assurance-scan/reports/\n"
    ".assurance-scan/findings.latest.json\n"
)


# ---------------------------------------------------------------------------
# Severity normalisation
# ---------------------------------------------------------------------------

def _normalise_severity(raw: str | None) -> str:
    if not raw:
        return "UNKNOWN"
    s = str(raw).strip().upper()
    aliases = {
        "BLOCKER": "CRITICAL",
        "FATAL": "CRITICAL",
        "ERR": "HIGH",
        "ERROR": "HIGH",
        "WARN": "MEDIUM",
        "WARNING": "MEDIUM",
        "INFO": "LOW",
        "INFORMATIONAL": "LOW",
        "NOTE": "LOW",
    }
    s = aliases.get(s, s)
    if s in SEVERITY_RANK:
        return s
    return "UNKNOWN"


SEMGREP_LEVEL_TO_SEVERITY = {
    "error": "HIGH",
    "warning": "MEDIUM",
    "note": "LOW",
    "none": "UNKNOWN",
}


# ---------------------------------------------------------------------------
# fix_strategy classifier
# ---------------------------------------------------------------------------

# Evaluated in order; first match wins. Default is "assisted".
STRATEGY_RULES: list[tuple[re.Pattern[str], str, str]] = [
    # (scanner_anchored_pattern, rule_id_pattern, strategy)
    # Gitleaks: history vs working-copy distinction is handled by the caller
    # via in_git_history; the rule pattern is only a secondary refinement.
    (re.compile(r"^gitleaks$", re.I), re.compile(r".", re.S), "manual-or-assisted"),
    # Hardcoded credential literals — high-entropy tokens can't be auto-fixed.
    (re.compile(r".", re.S), re.compile(r"hardcoded[-_](secret|api[_-]?key|password|token)", re.I), "manual"),
    (re.compile(r".", re.S), re.compile(r"(aws|gcp|azure)[-_](access[_-]?)?key[_-]?id", re.I), "manual"),
    (re.compile(r".", re.S), re.compile(r"private[_-]?key", re.I), "manual"),
    # Semgrep auto-fixable families
    (re.compile(r"^semgrep$", re.I), re.compile(r"eval[-_]?with[-_]?expression", re.I), "auto"),
    (re.compile(r"^semgrep$", re.I), re.compile(r"dangerous[-_]?subprocess[-_]?use", re.I), "auto"),
    (re.compile(r"^semgrep$", re.I), re.compile(r"hardcoded[-_]?password", re.I), "auto"),
    (re.compile(r"^semgrep$", re.I), re.compile(r"request[-_]?without[-_]?cert[-_]?verification", re.I), "auto"),
    (re.compile(r"^semgrep$", re.I), re.compile(r"verify\s*=\s*false", re.I), "auto"),
    (re.compile(r"^semgrep$", re.I), re.compile(r"xxe[-_]?etree[-_]?parse", re.I), "auto"),
    (re.compile(r"^semgrep$", re.I), re.compile(r"tarfile[-_]?extraction", re.I), "auto"),
    (re.compile(r"^semgrep$", re.I), re.compile(r"weak[-_]?hash[-_]?(md5|sha1)", re.I), "auto"),
    (re.compile(r"^semgrep$", re.I), re.compile(r"md5[-_]?used[-_]?for[-_]?password", re.I), "auto"),
    (re.compile(r"^semgrep$", re.I), re.compile(r"sql[-_]?string[-_]?concatenation", re.I), "auto"),
    # Trivy config — version bumps and policy choices need a human decision
    (re.compile(r"^trivy[-_]?config$", re.I), re.compile(r"(CVE|VULN|DS\d{3}|KHV|AVD)", re.I), "assisted"),
    (re.compile(r"^trivy[-_]?config$", re.I), re.compile(r"(tls|ssl)[-_]?(version|cipher)", re.I), "assisted"),
    (re.compile(r"^trivy[-_]?config$", re.I), re.compile(r"user[-_]?root|no[-_]?user", re.I), "assisted"),
    (re.compile(r"^trivy[-_]?config$", re.I), re.compile(r"privileged", re.I), "assisted"),
    (re.compile(r"^trivy[-_]?config$", re.I), re.compile(r"docker[-_]?socket", re.I), "assisted"),
]


def classify_fix_strategy(
    scanner: str,
    rule_id: str,
    *,
    file: str | None,
    snippet: str | None,
    in_git_history: bool | None = None,
) -> str:
    """Return 'auto' | 'assisted' | 'manual'.

    Gitleaks findings are special-cased: 'manual' if the secret is in git
    history (needs rotation + history rewrite), 'assisted' if working-copy
    only (line can be removed). Pass `in_git_history=None` to default to
    'manual' for safety.
    """
    scanner_norm = scanner or ""
    if scanner_norm.lower() == "gitleaks":
        if in_git_history is True:
            return "manual"
        if in_git_history is False:
            return "assisted"
        return "manual"  # unknown — safest

    rule_id_norm = rule_id or ""
    for scanner_re, rule_re, strategy in STRATEGY_RULES:
        if scanner_re.pattern == "." or scanner_re.match(scanner_norm):
            if rule_re.search(rule_id_norm) or rule_re.search(snippet or ""):
                if strategy == "manual-or-assisted":
                    return "manual" if in_git_history is not False else "assisted"
                return strategy
    return "assisted"


# ---------------------------------------------------------------------------
# Theme grouping
# ---------------------------------------------------------------------------

THEME_OVERRIDES: dict[str, str] = {
    "eval-with-expression": "eval",
    "dangerous-subprocess-use": "dangerous-subprocess",
    "hardcoded-password": "hardcoded-credentials",
    "hardcoded-secret": "hardcoded-credentials",
    "hardcoded-api-key": "hardcoded-credentials",
    "hardcoded-api_key": "hardcoded-credentials",
    "request-without-cert-verification": "tls-verification",
    "verify=false": "tls-verification",
    "xxe-etree-parse": "xxe",
    "tarfile-extraction": "unsafe-archive-extraction",
    "weak-hash-md5": "weak-crypto",
    "weak-hash-sha1": "weak-crypto",
    "md5-used-for-password": "weak-crypto",
    "sql-string-concatenation": "sql-injection",
}


def theme_for(scanner: str, rule_id: str) -> str:
    """Return f"{scanner}:{rule_family}". Stable across runs."""
    scanner_norm = (scanner or "unknown").lower().replace("_", "-")
    rid = (rule_id or "").lower()
    for key, family in THEME_OVERRIDES.items():
        if key in rid:
            return f"{scanner_norm}:{family}"
    # Derive a short family from the rule id: take the last 1-2 dot segments
    # that look like meaningful words.
    parts = [p for p in re.split(r"[._\-/]+", rid) if p]
    meaningful = [p for p in parts if p not in {"security", "audit", "lang", "detect", "generic"}]
    if not meaningful:
        meaningful = parts
    if not meaningful:
        return f"{scanner_norm}:general"
    family = meaningful[-1] if len(meaningful) == 1 else f"{meaningful[-2]}-{meaningful[-1]}"
    return f"{scanner_norm}:{family}"


# ---------------------------------------------------------------------------
# Git history probe (for gitleaks classification)
# ---------------------------------------------------------------------------

def is_in_git_history(file: str | None, source_repo: str | Path) -> bool:
    """Return True if the file is tracked in git (i.e. finding is in history)."""
    if not file:
        return True  # conservative default
    try:
        result = subprocess.run(
            ["git", "-C", str(source_repo), "ls-files", "--error-unmatch", file],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return True  # conservative


# ---------------------------------------------------------------------------
# Scanner parsers
# ---------------------------------------------------------------------------

def _snippet_lines(text: str | None, max_lines: int = 3) -> str:
    if not text:
        return ""
    cleaned = text.rstrip()
    if not cleaned:
        return ""
    lines = cleaned.splitlines()
    if len(lines) <= max_lines:
        return cleaned
    return "\n".join(lines[:max_lines]) + " …"


def parse_semgrep(sarif: dict[str, Any], *, snapshot_root, source_repo, source_repo_for_git) -> list[dict[str, Any]]:
    runs = sarif.get("runs") or []
    if not runs:
        return []
    run = runs[0]
    tool_rules = {}
    driver = (run.get("tool") or {}).get("driver") or {}
    for rule in driver.get("rules") or []:
        rid = rule.get("id")
        if rid:
            tool_rules[rid] = rule
    out: list[dict[str, Any]] = []
    for result in run.get("results") or []:
        rule_id = result.get("ruleId") or ""
        rule_meta = tool_rules.get(rule_id, {})
        level = (result.get("level") or "warning").lower()
        severity = SEMGREP_LEVEL_TO_SEVERITY.get(level, "MEDIUM")
        if rule_meta.get("defaultConfiguration", {}).get("level"):
            severity = SEMGREP_LEVEL_TO_SEVERITY.get(
                rule_meta["defaultConfiguration"]["level"].lower(), severity
            )
        message = (result.get("message") or {}).get("text") or ""
        short_desc = (rule_meta.get("shortDescription") or {}).get("text") or message
        full_desc = (rule_meta.get("fullDescription") or {}).get("text") or short_desc
        help_uri = ""
        for href_key in ("helpUri", "help_uri"):
            if rule_meta.get(href_key):
                help_uri = rule_meta[href_key]
                break

        locs = result.get("locations") or []
        if not locs:
            continue
        phys = locs[0].get("physicalLocation") or {}
        artifact = (phys.get("artifactLocation") or {}).get("uri") or ""
        region = phys.get("region") or {}
        line_start = region.get("startLine")
        line_end = region.get("endLine") or line_start
        snippet = region.get("snippet", {}).get("text") if isinstance(region.get("snippet"), dict) else None

        try:
            file_rel = remap_snapshot_path(
                artifact, snapshot_root=snapshot_root, source_repo=source_repo
            )
        except ValueError:
            continue
        if not file_rel:
            continue

        out.append({
            "scanner": "semgrep",
            "rule_id": rule_id,
            "rule_desc": short_desc,
            "rule_desc_long": full_desc,
            "help_uri": help_uri,
            "severity": severity,
            "file": file_rel,
            "line_start": line_start,
            "line_end": line_end,
            "snippet": _snippet_lines(snippet),
            "message": message,
            "in_git_history": is_in_git_history(file_rel, source_repo_for_git),
            "raw": {"artifact": artifact},
        })
    return out


def parse_gitleaks(findings: list[Any] | dict[str, Any], *, snapshot_root, source_repo, source_repo_for_git) -> list[dict[str, Any]]:
    if isinstance(findings, dict):
        items = findings.get("findings") or findings.get("Results") or []
    else:
        items = findings or []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rule_id = item.get("RuleID") or item.get("Rule") or "gitleaks"
        severity = _normalise_severity(item.get("Severity") or item.get("Severity") or "HIGH")
        file_path = item.get("File") or item.get("file") or ""
        try:
            file_rel = remap_snapshot_path(
                file_path, snapshot_root=snapshot_root, source_repo=source_repo
            )
        except ValueError:
            continue
        if not file_rel:
            continue
        line_start = item.get("StartLine") or item.get("StartLine")
        line_end = item.get("EndLine") or item.get("EndLine") or line_start
        secret = item.get("Secret") or ""
        snippet = item.get("Match") or item.get("Line") or ""
        description = item.get("Description") or f"Possible secret leaked: {rule_id}"
        # Mask the secret value for safe display in the agent skill.
        masked = re.sub(r"(.{4}).+(.{4})$", r"\1…\2", secret) if len(secret) > 12 else "***"
        out.append({
            "scanner": "gitleaks",
            "rule_id": rule_id,
            "rule_desc": description,
            "rule_desc_long": description,
            "help_uri": item.get("URL") or item.get("Url") or "",
            "severity": severity,
            "file": file_rel,
            "line_start": line_start,
            "line_end": line_end,
            "snippet": _snippet_lines(snippet),
            "message": f"Secret detected ({masked}). Rotate immediately if real.",
            "in_git_history": is_in_git_history(file_rel, source_repo_for_git),
            "raw": {"artifact": file_path, "fingerprint": item.get("Fingerprint", "")},
        })
    return out


def parse_trivy_config(data: dict[str, Any], *, snapshot_root, source_repo, source_repo_for_git) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for result in data.get("Results") or []:
        target = result.get("Target") or ""
        # Trivy config Target is usually a repo-relative file (Dockerfile, k8s manifest, etc.)
        # If it's a file, remap; if it's something else (e.g. "CloudFormation"), keep as-is.
        try:
            target_rel = remap_snapshot_path(
                target, snapshot_root=snapshot_root, source_repo=source_repo
            )
        except ValueError:
            target_rel = target  # leave as-is for non-file targets
        if not target_rel:
            target_rel = target
        for mis in result.get("Misconfigurations") or []:
            rule_id = mis.get("ID") or mis.get("AVDID") or "trivy-config"
            severity = _normalise_severity(mis.get("Severity"))
            title = mis.get("Title") or rule_id
            desc = mis.get("Description") or mis.get("Message") or title
            cause = mis.get("CauseMetadata") or {}
            line_start = cause.get("StartLine") or mis.get("StartLine")
            line_end = cause.get("EndLine") or mis.get("EndLine") or line_start
            resolution = mis.get("Resolution") or ""
            out.append({
                "scanner": "trivy-config",
                "rule_id": rule_id,
                "rule_desc": title,
                "rule_desc_long": desc,
                "help_uri": "",
                "severity": severity,
                "file": target_rel,
                "line_start": line_start,
                "line_end": line_end,
                "snippet": _snippet_lines(resolution),
                "message": mis.get("Message") or desc,
                "in_git_history": is_in_git_history(target_rel, source_repo_for_git),
                "raw": {"artifact": target, "resolution": resolution},
            })
    return out


# ---------------------------------------------------------------------------
# Compliance join from graph-manifest.json
# ---------------------------------------------------------------------------

def build_compliance_lookup(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build {(scanner, rule_id): [compliance_entries]} from graph evidence nodes."""
    lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    nodes = graph.get("nodes") or graph.get("graph", {}).get("nodes") or []
    for node in nodes:
        node_value = node.get("value") if isinstance(node, dict) and isinstance(node.get("value"), dict) else node
        if not isinstance(node_value, dict):
            continue
        ntype = node_value.get("type") or node_value.get("node_type") or ""
        if ntype not in {"scanner_result", "evidence"} and not node_value.get("scanner") and not node_value.get("tool"):
            continue
        scanner = node_value.get("scanner") or node_value.get("tool") or ""
        rule_id = node_value.get("rule_id") or node_value.get("ruleId") or ""
        if not scanner or not rule_id:
            continue
        key = (str(scanner).lower(), str(rule_id).lower())
        lookup[key].append({
            "mapping_id": node_value.get("ref") or node_value.get("mapping_id") or "",
            "ruleset": node_value.get("ruleset") or "",
            "row": node_value.get("row") or "",
            "mapping_level": node_value.get("mapping_level") or "",
            "traceability_strength": node_value.get("traceability_strength") or "",
        })
    return dict(lookup)


def attach_compliance(findings: list[dict[str, Any]], lookup: dict[str, list[dict[str, Any]]]) -> None:
    for f in findings:
        key = (f["scanner"].lower(), (f.get("rule_id") or "").lower())
        entries = lookup.get(key) or []
        seen = set()
        deduped = []
        for entry in entries:
            sig = (entry["mapping_id"], entry["ruleset"], entry["row"])
            if sig in seen or not any(sig):
                continue
            seen.add(sig)
            deduped.append(entry)
        f["compliance"] = deduped


# ---------------------------------------------------------------------------
# Main rollup
# ---------------------------------------------------------------------------

def _stable_id(scanner: str, rule_id: str, file: str, line_start: Any) -> str:
    raw = f"{scanner}|{rule_id}|{file}|{line_start}"
    # This is a persisted, non-cryptographic compatibility identifier. Changing
    # the algorithm would make existing findings appear unrelated to new scans.
    return hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
        raw.encode("utf-8")
    ).hexdigest()[:12]


def _default_remediation(finding: dict[str, Any]) -> str:
    scanner = finding["scanner"]
    rule_id = (finding.get("rule_id") or "").lower()
    finding.get("fix_strategy")
    if scanner == "gitleaks":
        if finding.get("in_git_history"):
            return (
                "Rotate the leaked credential immediately. Remove from working tree AND "
                "rewrite git history with `git filter-repo` or BFG. Force-push only after "
                "confirming rotation."
            )
        return "Remove the secret from the file and rotate it if it has ever been committed."
    if scanner == "semgrep":
        if "eval" in rule_id:
            return "Replace eval(expr) with Function constructor or a fixed dispatcher; never eval untrusted input."
        if "subprocess" in rule_id:
            return "Pass argv list (no shell=True); validate/escape any dynamic components."
        if "verify=false" in rule_id or "cert-verification" in rule_id:
            return "Remove verify=False (or set verify=True) so TLS is actually validated."
        if "xxe" in rule_id:
            return "Disable external entity resolution: defusedxml, or set XMLParser(resolve_entities=False)."
        if "tarfile" in rule_id:
            return "Use a safe extractor that rejects absolute paths and `..` traversal members."
        if "md5" in rule_id or "sha1" in rule_id:
            return "Replace weak hash with SHA-256 (or password_hash/bcrypt for passwords)."
        if "sql" in rule_id and "concat" in rule_id:
            return "Use parameterised queries; do not interpolate user input into SQL strings."
    if scanner == "trivy-config":
        return finding.get("snippet") or finding.get("rule_desc_long") or finding.get("rule_desc") or ""
    return finding.get("rule_desc_long") or finding.get("rule_desc") or ""


def build_findings_json(
    report_dir: Path,
    *,
    source_repo: str | Path,
    snapshot_root: str | Path,
) -> dict[str, Any]:
    """Read scanner outputs + manifests and build the rolled-up findings dict."""
    findings: list[dict[str, Any]] = []

    semgrep_path = report_dir / "reports" / "semgrep.sarif"
    if semgrep_path.exists():
        sarif = load_json(semgrep_path) or {}
        findings.extend(parse_semgrep(
            sarif,
            snapshot_root=snapshot_root,
            source_repo=source_repo,
            source_repo_for_git=source_repo,
        ))

    gitleaks_path = report_dir / "reports" / "gitleaks.json"
    if gitleaks_path.exists():
        gl = load_json(gitleaks_path)
        if gl is not None:
            findings.extend(parse_gitleaks(
                gl,
                snapshot_root=snapshot_root,
                source_repo=source_repo,
                source_repo_for_git=source_repo,
            ))

    trivy_path = report_dir / "reports" / "trivy-config.json"
    if trivy_path.exists():
        tv = load_json(trivy_path) or {}
        findings.extend(parse_trivy_config(
            tv,
            snapshot_root=snapshot_root,
            source_repo=source_repo,
            source_repo_for_git=source_repo,
        ))

    # Compliance join
    graph_path = report_dir / "graph-manifest.json"
    if graph_path.exists():
        graph = load_json(graph_path) or {}
        attach_compliance(findings, build_compliance_lookup(graph))
    else:
        for f in findings:
            f["compliance"] = []

    # Classify fix_strategy + theme + stable id + remediation
    for f in findings:
        f["fix_strategy"] = classify_fix_strategy(
            f["scanner"],
            f.get("rule_id") or "",
            file=f.get("file"),
            snippet=f.get("snippet"),
            in_git_history=f.get("in_git_history"),
        )
        f["theme"] = theme_for(f["scanner"], f.get("rule_id") or "")
        f["id"] = _stable_id(f["scanner"], f.get("rule_id") or "", f.get("file") or "", f.get("line_start"))
        f["remediation"] = _default_remediation(f)

    # Sort findings by severity, then file, then line
    findings.sort(key=lambda f: (
        SEVERITY_RANK.get(f.get("severity", "UNKNOWN"), 99),
        f.get("file") or "",
        f.get("line_start") or 0,
    ))

    # Summary
    distinct_files = {f["file"] for f in findings if f.get("file")}
    by_severity = Counter(f.get("severity", "UNKNOWN") for f in findings)
    by_scanner = Counter(f["scanner"] for f in findings)
    by_strategy = Counter(f["fix_strategy"] for f in findings)
    by_theme = Counter(f["theme"] for f in findings)

    severity_weight = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}
    themes_ranked = sorted(
        by_theme.items(),
        key=lambda kv: (-sum(
            severity_weight.get(g.get("severity", "UNKNOWN"), 0)
            for g in findings
            if g["theme"] == kv[0]
        ), kv[0]),
    )
    pr_strategy = "single" if len(distinct_files) <= PR_STRATEGY_SINGLE_FILE_THRESHOLD else "themed"

    # Git context from evidence-manifest.json
    evidence_manifest = load_json(report_dir / "evidence-manifest.json") or {}
    git_context = evidence_manifest.get("git") or evidence_manifest.get("source") or {}

    return {
        "schema_version": "1.0",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "run_id": evidence_manifest.get("run_id", report_dir.name),
        "source_repo": str(source_repo),
        "git_branch": git_context.get("branch") or git_context.get("git_branch") or "",
        "git_commit": git_context.get("commit") or git_context.get("git_commit") or "",
        "safe_scan_branch": git_context.get("safe_scan_branch") or "",
        "scanner_health": _scanner_health(report_dir),
        "summary": {
            "total_findings": len(findings),
            "distinct_files": len(distinct_files),
            "pr_strategy": pr_strategy,
            "pr_strategy_threshold": PR_STRATEGY_SINGLE_FILE_THRESHOLD,
            "by_severity": {sev: by_severity.get(sev, 0) for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]},
            "by_scanner": dict(sorted(by_scanner.items())),
            "by_fix_strategy": {k: by_strategy.get(k, 0) for k in ["auto", "assisted", "manual"]},
            "by_theme": dict(sorted(by_theme.items())),
            "themes_ranked": [t for t, _ in themes_ranked],
        },
        "findings": findings,
    }


def _scanner_health(report_dir: Path) -> dict[str, str]:
    health: dict[str, str] = {}
    raw_dir = report_dir / "reports"
    for scanner, fname in [
        ("semgrep", "semgrep.sarif"),
        ("gitleaks", "gitleaks.json"),
        ("trivy-config", "trivy-config.json"),
    ]:
        p = raw_dir / fname
        if not p.exists():
            health[scanner] = "MISSING"
        elif p.stat().st_size == 0:
            health[scanner] = "EMPTY"
        else:
            health[scanner] = "PASS"
    return health


# ---------------------------------------------------------------------------
# Filesystem operations
# ---------------------------------------------------------------------------

def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    json.dump(payload, buf, indent=2, ensure_ascii=False)
    buf.write("\n")
    path.write_text(buf.getvalue())


def copy_raw_reports(report_dir: Path, publish_dir: Path) -> list[str]:
    """Copy essential report files to the publish dir. Returns list of copied rel paths."""
    copied: list[str] = []
    publish_dir.mkdir(parents=True, exist_ok=True)
    raw_src = report_dir / "reports"
    raw_dst = publish_dir / "reports"
    raw_dst.mkdir(exist_ok=True)
    for fname in ["semgrep.sarif", "gitleaks.json", "trivy-config.json"]:
        src = raw_src / fname
        if src.exists():
            shutil.copy2(src, raw_dst / fname)
            copied.append(f"reports/{fname}")
    for fname in ["evidence-manifest.json", "executive-summary.md", "scanner-run-summary.txt", "graph-manifest.json"]:
        src = report_dir / fname
        if src.exists():
            shutil.copy2(src, publish_dir / fname)
            copied.append(fname)
    return copied


def ensure_gitignored(source_repo: Path, mode: str, *, stdin_tty: bool | None = None) -> str:
    """Idempotently append the assurance-scan block to the user's .gitignore.

    Returns 'appended' | 'present' | 'skipped' | 'fallback-auto'.
    """
    is_tty = sys.stdin.isatty() if stdin_tty is None else stdin_tty
    gitignore = source_repo / ".gitignore"

    existing = gitignore.read_text(errors="replace") if gitignore.exists() else ""
    if GITIGNORE_MARKER in existing:
        return "present"

    if mode == "skip":
        return "skipped"
    if mode == "prompt":
        if not is_tty:
            mode = "auto"
        else:
            answer = input(
                f"Append '{GITIGNORE_MARKER}' to {gitignore}? [y/N] "
            ).strip().lower()
            if answer not in {"y", "yes"}:
                return "skipped"

    # mode == "auto" (or prompt that fell back)
    block = GITIGNORE_BLOCK if existing and not existing.endswith("\n") else GITIGNORE_BLOCK.lstrip("\n")
    with gitignore.open("a") as fh:
        fh.write(block)
    return "appended" if mode == "auto" else "fallback-auto"


def maybe_install_agent_skill(source_repo: Path, script_dir: Path, *, force: bool = False) -> str:
    """Copy the slash-command template into the user's repo. Idempotent.

    Returns 'installed' | 'present' | 'missing-template'.
    """
    template = script_dir.parent / AGENT_SKILL_REL_PATH
    if not template.exists():
        return "missing-template"
    target = source_repo / AGENT_SKILL_INSTALL_REL_PATH
    if target.exists() and not force:
        return "present"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, target)
    return "installed"


def _resolve_publish_dir(report_dir: Path, publish_root: str | Path, run_id: str) -> Path:
    return Path(publish_root) / PUBLISH_DIRNAME / run_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--publish-dir", required=True, type=Path,
                        help="Final publish dir for this run (already includes run id).")
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--gitignore-mode", default="auto", choices=["auto", "prompt", "skip"])
    parser.add_argument("--no-agent-skill", action="store_true")
    parser.add_argument("--force-agent-skill", action="store_true",
                        help="Overwrite the agent skill if it already exists.")
    args = parser.parse_args(argv)

    report_dir = args.report_dir.resolve()
    source_repo = args.source_repo.resolve()
    publish_dir = args.publish_dir.resolve()
    snapshot_root = args.snapshot_root.resolve()

    if not report_dir.is_dir():
        print(f"publish-findings: report dir not found: {report_dir}", file=sys.stderr)
        return 2
    if not source_repo.is_dir():
        print(f"publish-findings: source repo not found: {source_repo}", file=sys.stderr)
        return 2

    def log(msg):
        return print(f"publish-findings: {msg}")

    log(f"building findings rollup from {report_dir}")
    payload = build_findings_json(
        report_dir,
        source_repo=source_repo,
        snapshot_root=snapshot_root,
    )

    publish_dir.mkdir(parents=True, exist_ok=True)
    write_json(publish_dir / "findings.json", payload)
    log(f"wrote {publish_dir / 'findings.json'}")

    # Stable latest pointer — at the .assurance-scan/ root, two levels above the per-run dir.
    # publish_dir layout: <source_repo>/.assurance-scan/reports/<run_id>/
    # We want: <source_repo>/.assurance-scan/findings.latest.json
    dot_assurance = source_repo / ".assurance-scan"
    publish_root = publish_dir.parent.parent.resolve()
    if publish_dir.parent.name == PUBLISH_DIRNAME and publish_root == dot_assurance.resolve():
        latest = dot_assurance / LATEST_POINTER_NAME
        write_json(latest, payload)
        log(f"wrote {latest}")

    copied = copy_raw_reports(report_dir, publish_dir)
    if copied:
        log(f"copied {len(copied)} supporting file(s)")

    # Gitignore handling
    gi_status = ensure_gitignored(source_repo, args.gitignore_mode)
    if gi_status == "appended":
        log(f"appended '{GITIGNORE_MARKER}' to {source_repo / '.gitignore'}")
    elif gi_status == "fallback-auto":
        log(f"prompt mode fell back to auto; appended to {source_repo / '.gitignore'}")
    elif gi_status == "present":
        log(f".gitignore already ignores '{GITIGNORE_MARKER}'")
    elif gi_status == "skipped":
        log(f"gitignore update skipped (mode={args.gitignore_mode}); user must ignore '{GITIGNORE_MARKER}' manually")

    # Agent skill install
    if not args.no_agent_skill:
        skill_status = maybe_install_agent_skill(
            source_repo, Path(__file__).resolve().parent, force=args.force_agent_skill
        )
        if skill_status == "installed":
            log(f"installed agent skill at {source_repo / AGENT_SKILL_INSTALL_REL_PATH}")
        elif skill_status == "present":
            log("agent skill already present (not overwritten)")
        elif skill_status == "missing-template":
            log("WARN: agent skill template not found in scanner bundle; skipping install")

    # Console summary for the wrapper to surface
    summary = payload["summary"]
    print(
        f"publish-findings: {summary['total_findings']} findings "
        f"({summary['by_severity'].get('CRITICAL', 0)}C/"
        f"{summary['by_severity'].get('HIGH', 0)}H/"
        f"{summary['by_severity'].get('MEDIUM', 0)}M/"
        f"{summary['by_severity'].get('LOW', 0)}L) "
        f"across {summary['distinct_files']} files → "
        f"pr_strategy={summary['pr_strategy']} → "
        f"{publish_dir / 'findings.json'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
