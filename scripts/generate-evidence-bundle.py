#!/usr/bin/env python3
"""Phase 4 — Evidence bundle generator.

Reads:
  - <report_dir>/scanner-health.json  (per-scanner PASS/WARN/FAIL/SKIPPED)
  - <report_dir>/config-status.json   (preflight INFO/WARNING/ERROR)
  - <report_dir>/reports/*            (raw scanner outputs)
  - <report_dir>/sbom/*               (SBOMs)
  - <report_dir>/manual-evidence-required.md (counts PENDING items)
  - git rev-parse HEAD in $TARGET_DIR (best-effort)

Writes:
  - <report_dir>/hashes/<file>.sha256
  - <report_dir>/evidence-manifest.json
  - <report_dir>/evidence-bundle.json
  - <report_dir>/executive-summary.md
  - <report_dir>/scanner-run-summary.txt
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from defusedxml import ElementTree as ET
from pathlib import Path

from artifact_hashing import file_sha256, write_hash_sidecar

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")

# Scanner name → expected output file (relative to reports/ or sbom/)
LEVEL1_SCANNERS = [
    {"name": "semgrep",            "output": "reports/semgrep.sarif",        "format": "sarif",   "level": 1, "image": "semgrep/semgrep:latest"},
    {"name": "gitleaks",           "output": "reports/gitleaks.json",       "format": "json",    "level": 1, "image": "zricethezav/gitleaks:latest"},
    {"name": "trivy-fs",           "output": "reports/trivy-fs.json",       "format": "trivy",   "level": 1, "image": "aquasec/trivy:latest"},
    {"name": "trivy-config",       "output": "reports/trivy-config.json",   "format": "trivy",   "level": 1, "image": "aquasec/trivy:latest"},
    {"name": "syft",               "output": "sbom/sbom.cyclonedx.json",    "format": "cyclonedx", "level": 1, "image": "anchore/syft:latest"},
    {"name": "grype",              "output": "reports/grype.json",          "format": "grype",   "level": 1, "image": "anchore/grype:latest"},
    {"name": "osv-scanner",        "output": "reports/osv-scanner.json",    "format": "osv",     "level": 1, "image": "ghcr.io/google/osv-scanner:latest"},
]
LEVEL2_SCANNERS = [
    {"name": "trivy-image",        "output": "reports/trivy-image.json",       "format": "trivy",    "level": 2, "flag": "image", "image": "aquasec/trivy:latest"},
    {"name": "syft-image",         "output": "sbom/image-sbom.cyclonedx.json", "format": "cyclonedx", "level": 2, "flag": "image", "image": "anchore/syft:latest"},
    {"name": "grype-image",        "output": "reports/grype-image.json",       "format": "grype",   "level": 2, "flag": "image", "image": "anchore/grype:latest"},
    {"name": "zap-baseline",       "output": "reports/zap-baseline.json",      "format": "zap",     "level": 2, "flag": "url",   "image": "ghcr.io/zaproxy/zaproxy:stable"},
    {"name": "security-headers",   "output": "reports/security-headers.json",  "format": "headers", "level": 2, "flag": "url",   "image": "python:3.12-slim"},
    {"name": "testssl",            "output": "reports/testssl.jsonl",          "format": "testssl", "level": 2, "flag": "https", "image": "drwetter/testssl:latest"},
    {"name": "clamav",             "output": "reports/clamav.txt",             "format": "clamav",  "level": 2, "flag": "uploads", "image": "clamav/clamav:latest"},
]


def _xml_attrs(text: str) -> dict[str, str]:
    return {
        str(match.group(1)): str(match.group(2) or match.group(3) or "")
        for match in re.finditer(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""", text)
    }


def _junit_failure_status(raw_status: str, diagnostic: str) -> str:
    if raw_status != "failed":
        return raw_status
    text = diagnostic.lower()
    harness_markers = (
        "cannot find module",
        "cannot find native binding",
        "module_not_found",
        "syntaxerror",
        "referenceerror",
        "typeerror: ",
        "npm has a bug related to optional dependencies",
        "test suite failed to run",
        "your test suite must contain at least one test",
        "environment teardown",
    )
    if any(marker in text for marker in harness_markers):
        return "execution_error"
    return "failed"


def _junit_case_records(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        root = ET.parse(path).getroot()
        cases = []
        for case in root.iter("testcase"):
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            body_status = "failed" if failure is not None or error is not None else "missing" if skipped is not None else "passed"
            elem = failure if failure is not None else error if error is not None else skipped
            message = (elem.get("message") if elem is not None else "") or ("Skipped" if skipped is not None else "")
            diagnostic = (elem.text if elem is not None else "") or ""
            status = _junit_failure_status(body_status, " ".join(part for part in (message, diagnostic) if part))
            cases.append({
                "name": case.get("name", ""),
                "classname": case.get("classname", ""),
                "file": case.get("file", ""),
                "status": status,
                "message": message,
                "diagnostic": diagnostic,
            })
        return cases
    except Exception:
        text = path.read_text(errors="replace")
        cases = []
        pattern = re.compile(r"<testcase\b([^>]*)>(.*?)</testcase>|<testcase\b([^>]*)/>", re.IGNORECASE | re.DOTALL)
        for match in pattern.finditer(text):
            attrs = _xml_attrs(match.group(1) or match.group(3) or "")
            body = match.group(2) or ""
            if re.search(r"<(?:failure|error)\b", body, re.IGNORECASE):
                status = "failed"
            elif re.search(r"<skipped\b", body, re.IGNORECASE):
                status = "missing"
            else:
                status = "passed"
            message_match = re.search(r"<(?:failure|error|skipped)\b([^>]*)", body, re.IGNORECASE)
            message = _xml_attrs(message_match.group(1)).get("message", "") if message_match else ""
            diagnostic = re.sub(r"<[^>]+>", " ", body).strip()
            status = _junit_failure_status(status, " ".join(part for part in (message, diagnostic) if part))
            cases.append({
                "name": attrs.get("name", ""),
                "classname": attrs.get("classname", ""),
                "file": attrs.get("file", ""),
                "status": status,
                "message": message or ("Skipped" if status == "missing" else ""),
                "diagnostic": diagnostic,
            })
        return cases


def load_json(path: Path):
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(errors="replace"))
    except Exception:
        return None
    return None


def count_trivy(path: Path) -> dict:
    counts = {s: 0 for s in SEVERITIES}
    data = load_json(path)
    if not data:
        return counts
    for result in data.get("Results", []) or []:
        for vuln in result.get("Vulnerabilities", []) or []:
            sev = str(vuln.get("Severity", "UNKNOWN")).upper()
            counts[sev if sev in counts else "UNKNOWN"] += 1
        for mis in result.get("Misconfigurations", []) or []:
            sev = str(mis.get("Severity", "UNKNOWN")).upper()
            counts[sev if sev in counts else "UNKNOWN"] += 1
        for _secret in result.get("Secrets", []) or []:
            counts["HIGH"] += 1
    return counts


def count_grype(path: Path) -> dict:
    counts = {s: 0 for s in SEVERITIES}
    data = load_json(path)
    if not data:
        return counts
    for match in data.get("matches", []) or []:
        sev = str(((match.get("vulnerability") or {}).get("severity")) or "UNKNOWN").upper()
        counts[sev if sev in counts else "UNKNOWN"] += 1
    return counts


def count_dependency_check(path: Path) -> dict:
    counts = {s: 0 for s in SEVERITIES}
    data = load_json(path)
    if not data:
        return counts
    for dep in data.get("dependencies", []) or []:
        for vuln in dep.get("vulnerabilities", []) or []:
            sev = str(vuln.get("severity", "UNKNOWN")).upper()
            counts[sev if sev in counts else "UNKNOWN"] += 1
    return counts


def count_osv(path: Path) -> dict:
    """OSV-scanner JSON: count vulnerabilities by severity (CVSS-based)."""
    counts = {s: 0 for s in SEVERITIES}
    data = load_json(path)
    if not data:
        return counts
    for result in data.get("results", []) or []:
        for pkg in result.get("packages", []) or []:
            for vuln in pkg.get("vulnerabilities", []) or []:
                sev = "UNKNOWN"
                # OSV severity_map keyed by CVSS vector name
                sm = vuln.get("severity") or []
                if isinstance(sm, list) and sm:
                    # Take first CVSS score
                    cvss_str = (sm[0].get("score") or "").upper()
                    if "CVSS" in cvss_str:
                        # Try to extract numeric score
                        import re
                        m = re.search(r"CVSS[\d.]*:?\s*([0-9.]+)", cvss_str)
                        if m:
                            try:
                                score = float(m.group(1))
                                if score >= 9.0:
                                    sev = "CRITICAL"
                                elif score >= 7.0:
                                    sev = "HIGH"
                                elif score >= 4.0:
                                    sev = "MEDIUM"
                                elif score > 0:
                                    sev = "LOW"
                            except ValueError:
                                pass
                counts[sev] += 1
    return counts


def count_semgrep(path: Path) -> int:
    data = load_json(path)
    if not data:
        return 0
    total = 0
    for run in data.get("runs", []) or []:
        total += len(run.get("results", []) or [])
    return total


def count_gitleaks(path: Path) -> tuple[int, int]:
    """Return (total, high_count)."""
    data = load_json(path)
    if not isinstance(data, list):
        return 0, 0
    total = len(data)
    # gitleaks doesn't tag severity per finding; treat all as blocking-high.
    return total, total


def count_zap(path: Path) -> dict:
    counts = {s: 0 for s in SEVERITIES}
    data = load_json(path)
    if not data:
        return counts
    for site in data.get("site", []) or []:
        for alert in site.get("alerts", []) or []:
            sev = str(alert.get("riskdesc", "UNKNOWN")).split(" ")[0].upper()
            counts[sev if sev in counts else "UNKNOWN"] += 1
    return counts


def count_testssl(path: Path) -> dict:
    counts = {s: 0 for s in SEVERITIES}
    if not path.exists():
        return counts
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            rating = (obj.get("rating") or "").upper()
            sev_map = {"F": "CRITICAL", "C": "HIGH", "B": "MEDIUM", "A": "LOW"}
            sev = sev_map.get(rating[0] if rating else "", "UNKNOWN")
            if sev in counts:
                counts[sev] += 1
    except Exception:
        pass
    return counts


def count_security_headers(path: Path) -> dict:
    counts = {s: 0 for s in SEVERITIES}
    data = load_json(path)
    if not data:
        return counts
    for finding in data.get("findings", []) or []:
        if finding.get("status") == "MISSING":
            sev = str(finding.get("severity", "UNKNOWN")).upper()
            counts[sev if sev in counts else "UNKNOWN"] += 1
    return counts


def count_clamav(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        text = path.read_text(errors="replace")
        m = re.search(r"Infected files:\s*(\d+)", text)
        if m:
            return int(m.group(1))
        # clamscan with --infected lists each match
        return max(0, len([l for l in text.splitlines() if "FOUND" in l]))
    except Exception:
        return 0


def count_cyclonedx_components(path: Path) -> int:
    data = load_json(path)
    if not data:
        return 0
    return len(data.get("components", []) or [])


def fmt_counts(counts: dict) -> str:
    return ", ".join(f"{s.title()}: {counts.get(s, 0)}" for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"))


def add_counts(items: list[dict]) -> dict:
    out = {s: 0 for s in SEVERITIES}
    for item in items:
        for sev in SEVERITIES:
            out[sev] += item.get(sev, 0)
    return out


def output_candidates(scanner: dict, report_dir: Path) -> list[Path]:
    rel = Path(scanner["output"])
    base = report_dir / rel
    parent = base.parent
    name = base.name
    if name.endswith(".cyclonedx.json"):
        prefix = name[: -len(".cyclonedx.json")]
        suffix = ".cyclonedx.json"
    else:
        suffix = "".join(base.suffixes) or base.suffix
        prefix = name[: -len(suffix)] if suffix else name
    candidates = []
    if base.exists() and base.stat().st_size > 0:
        candidates.append(base)
    if scanner.get("level") == 2 and parent.is_dir():
        for path in sorted(parent.glob(f"{prefix}-*{suffix}")):
            if path.is_file() and path.stat().st_size > 0 and path not in candidates:
                candidates.append(path)
    return candidates


def target_word(n: int) -> str:
    return "target" if n == 1 else "targets"


def classify_health(scanner: dict, report_dir: Path, config_status: dict) -> tuple[str, str]:
    """Return (status, reason). status ∈ {PASS, WARN, FAIL, SKIPPED}."""
    output_paths = output_candidates(scanner, report_dir)
    output_path = report_dir / scanner["output"]
    name = scanner["name"]

    # Special-case first: osv-scanner writes no output when no lockfiles are
    # found. That's a project-shape limitation, not a scanner failure.
    if name == "osv-scanner" and not output_paths:
        run_log = report_dir / "run.log"
        sig = "No package sources found"
        if run_log.exists() and sig in run_log.read_text(errors="replace"):
            return ("WARN", "No lockfiles found — coverage limited; see Trivy FS / Grype")

    if not output_paths:
        return "FAIL", f"Output not produced: {scanner['output']}"

    n_targets = len(output_paths)
    prefix = f"{n_targets} {target_word(n_targets)}; " if n_targets > 1 else ""

    # Per-tool inspection
    if name == "semgrep":
        n = sum(count_semgrep(path) for path in output_paths)
        return ("WARN", f"{n} findings") if n else ("PASS", "No findings")
    if name == "gitleaks":
        totals = [count_gitleaks(path) for path in output_paths]
        total = sum(item[0] for item in totals)
        high = sum(item[1] for item in totals)
        return ("FAIL" if high else "PASS", f"{total} leaked secrets")
    if name in ("trivy-fs", "trivy-config", "trivy-image"):
        c = add_counts([count_trivy(path) for path in output_paths])
        crit = c["CRITICAL"]
        return ("FAIL" if crit else "WARN" if (c["HIGH"] or c["MEDIUM"]) else "PASS",
                prefix + fmt_counts(c))
    if name in ("grype", "grype-image"):
        c = add_counts([count_grype(path) for path in output_paths])
        crit = c["CRITICAL"]
        return ("FAIL" if crit else "WARN" if (c["HIGH"] or c["MEDIUM"]) else "PASS",
                prefix + fmt_counts(c))
    if name == "osv-scanner":
        c = add_counts([count_osv(path) for path in output_paths])
        crit = c["CRITICAL"]
        return ("FAIL" if crit else "WARN" if (c["HIGH"] or c["MEDIUM"]) else "PASS",
                fmt_counts(c))
    if name in ("syft", "syft-image"):
        n = sum(count_cyclonedx_components(path) for path in output_paths)
        return ("PASS", prefix + f"{n} components") if n else ("WARN", prefix + "Empty SBOM")
    if name == "zap-baseline":
        c = add_counts([count_zap(path) for path in output_paths])
        crit = c["CRITICAL"]
        return ("FAIL" if crit else "WARN" if (c["HIGH"] or c["MEDIUM"]) else "PASS",
                prefix + fmt_counts(c))
    if name == "testssl":
        c = add_counts([count_testssl(path) for path in output_paths])
        crit = c["CRITICAL"]
        return ("FAIL" if crit else "WARN" if c["HIGH"] else "PASS", prefix + fmt_counts(c))
    if name == "security-headers":
        c = add_counts([count_security_headers(path) for path in output_paths])
        crit = c["CRITICAL"]
        return ("FAIL" if crit else "WARN" if (c["HIGH"] or c["MEDIUM"]) else "PASS",
                prefix + fmt_counts(c))
    if name == "clamav":
        n = sum(count_clamav(path) for path in output_paths)
        return ("FAIL" if n else "PASS", prefix + f"{n} infected files")
    return ("PASS", prefix + "ran")


def get_git_commit(target_dir: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", target_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def get_git_branch(target_dir: str | None) -> str | None:
    if not target_dir:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", target_dir, "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return None


def get_git_repo_name(target_dir: str | None) -> str | None:
    if not target_dir:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", target_dir, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).name
    except Exception:
        pass
    return None


def junit_summary(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {"present": False, "tests": 0, "passed": 0, "failed": 0, "skipped": 0}
    cases = _junit_case_records(path)
    tests = len(cases)
    failed = sum(1 for case in cases if case.get("status") == "failed")
    execution_error = sum(1 for case in cases if case.get("status") == "execution_error")
    skipped = sum(1 for case in cases if case.get("status") == "missing")
    return {
        "present": True,
        "tests": tests,
        "passed": max(0, tests - failed - execution_error - skipped),
        "failed": failed,
        "execution_error": execution_error,
        "skipped": skipped,
        "path": "reports/junit.xml",
    }


def junit_records(path: Path) -> dict[str, dict]:
    if not path.exists() or path.stat().st_size == 0:
        return {}

    records: dict[str, dict] = {}
    for case in _junit_case_records(path):
        name = case.get("name", "")
        classname = case.get("classname", "")
        file_attr = case.get("file", "")
        status = case.get("status", "passed")
        message = case.get("message", "")
        diagnostic = case.get("diagnostic", "")
        record = {
            "status": status,
            "name": name,
            "classname": classname,
            "file": file_attr,
            "message": message,
            "diagnostic": diagnostic,
        }
        keys = {name}
        if classname and name:
            keys.update({f"{classname}.{name}", f"{classname}::{name}"})
        if file_attr and name:
            keys.add(f"{file_attr}::{name}")
            keys.add(f"{Path(file_attr).name}::{name}")
        for key in keys:
            if key:
                records[key] = record
    return records


def _junit_record_for_tbt(tbt: dict, records: dict[str, dict]) -> dict | None:
    candidates = [tbt.get("ref", ""), tbt.get("id", ""), tbt.get("title", "")]
    ref = tbt.get("ref", "")
    if "::" in ref:
        path, _, name = ref.partition("::")
        candidates.extend([name, f"{Path(path).name}::{name}"])
    for candidate in candidates:
        if candidate and candidate in records:
            return records[candidate]
    return None


def _safe_evidence_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    if not safe or not safe[0].isalpha():
        safe = f"EVD-{safe}"
    if not safe.startswith("EVD-"):
        safe = f"EVD-{safe}"
    return safe


SCHEMA_REFS = {
    "assurance_test_pack": "data/schemas/assurance-test-pack.schema.json",
    "evidence_bundle": "data/schemas/evidence-bundle.schema.json",
    "fr_catalog": "data/schemas/fr-catalog.schema.json",
    "json": "application/schema+json",
    "junit": "https://llg.cubic.org/docs/junit/",
    "sarif": "https://json.schemastore.org/sarif-2.1.0.json",
    "cyclonedx": "https://cyclonedx.org/schema",
    "test_source": "tests/asvs/<type>/<TBT-ID>.assurance.test.js",
}


def _artifact_ref(
    report_dir: Path,
    rel_path: str,
    *,
    fmt: str | None = None,
    locator: str | None = None,
    schema_ref: str | None = None,
) -> dict:
    artifact = {"path": rel_path}
    if fmt:
        artifact["format"] = fmt
        if not schema_ref:
            schema_ref = SCHEMA_REFS.get(fmt)
    if locator:
        artifact["locator"] = locator
    if schema_ref:
        artifact["schema_ref"] = schema_ref
    path = report_dir / rel_path
    if path.is_file():
        artifact["bytes"] = path.stat().st_size
        artifact["sha256"] = file_sha256(path)
    return artifact


def _provenance(
    *,
    collector: str,
    collected_at: str,
    output_artifacts: list[dict],
    tool: str | None = None,
    container_image: str | None = None,
    input_artifacts: list[dict] | None = None,
    normalizer: str | None = None,
) -> dict:
    provenance = {
        "collector": collector,
        "collected_at": collected_at,
        "output_artifacts": output_artifacts,
    }
    if tool:
        provenance["tool"] = tool
    if container_image:
        provenance["container_image"] = container_image
    if input_artifacts:
        provenance["input_artifacts"] = input_artifacts
    if normalizer:
        provenance["normalizer"] = normalizer
    return provenance


def _artifact_label(artifact: dict) -> str:
    return str(artifact.get("path") or artifact.get("locator") or artifact.get("source") or "").strip()


def _side_effect(type_: str, target: str, description: str, *, mode: str = "observed") -> dict:
    effect = {
        "type": type_,
        "target": target,
        "description": description,
        "mode": mode,
    }
    return {key: value for key, value in effect.items() if value}


def _test_actions_for_record(record: dict | None, tbt: dict, status: str, locator: str) -> list[dict]:
    tbt_id = str(tbt.get("id") or "")
    test_file = str((record or {}).get("file") or str(tbt.get("ref") or "").split("::", 1)[0])
    case_name = str((record or {}).get("name") or tbt_id)
    classname = str((record or {}).get("classname") or "")
    actions = [
        {
            "type": "testcase_execution",
            "name": case_name,
            "target": test_file or locator or tbt_id,
            "status": status,
            "description": "Executed the approved assurance testcase and captured its result in JUnit XML.",
        }
    ]
    if classname or locator:
        actions.append({
            "type": "junit_identity_recorded",
            "name": classname or case_name,
            "target": locator or case_name,
            "status": status,
            "description": "Recorded the TBT identifier in JUnit classname/name so the scanner can join evidence back to the FR/TBT graph.",
        })
    message = str((record or {}).get("message") or "")
    diagnostic = str((record or {}).get("diagnostic") or "")
    if status == "execution_error" and diagnostic:
        message = diagnostic
    if message:
        actions.append({
            "type": "diagnostic_recorded",
            "name": "test diagnostic",
            "target": case_name,
            "status": status,
            "description": message,
        })
    return actions


def _enrich_evidence_io(record: dict) -> dict:
    provenance = record.get("provenance") or {}
    inputs = list(record.get("inputs") or provenance.get("input_artifacts") or [])
    outputs = list(record.get("outputs") or provenance.get("output_artifacts") or record.get("raw_artifacts") or [])
    side_effects = list(record.get("side_effects") or [])
    effect_keys = {
        (str(item.get("type") or ""), str(item.get("target") or ""))
        for item in side_effects
        if isinstance(item, dict)
    }

    def add_effect(effect: dict) -> None:
        key = (str(effect.get("type") or ""), str(effect.get("target") or ""))
        if key not in effect_keys:
            effect_keys.add(key)
            side_effects.append(effect)

    if record.get("type") == "test_result":
        add_effect(_side_effect(
            "process_execution",
            str((provenance.get("tool") or record.get("tool") or "approved test runner")),
            "Runs the approved assurance test. The test is expected to be non-destructive and must not modify product behaviour.",
            mode="non_destructive",
        ))
    elif record.get("type") == "scanner_result":
        add_effect(_side_effect(
            "scanner_execution",
            str((provenance.get("tool") or record.get("tool") or "scanner")),
            "Runs or imports scanner output as read-only security evidence for the selected report.",
            mode="read_only_analysis",
        ))
    elif record.get("type") == "manual_note":
        add_effect(_side_effect(
            "review_record",
            str(record.get("source") or "manual evidence"),
            "Records a manual review requirement; no automated product action is performed.",
            mode="review_only",
        ))

    for artifact in outputs:
        target = _artifact_label(artifact)
        if target:
            add_effect(_side_effect(
                "file_write",
                target,
                "Writes or refreshes an evidence artifact used by the assurance report.",
            ))

    record["inputs"] = inputs
    record["outputs"] = outputs
    record["side_effects"] = side_effects
    record["test_actions"] = record.get("test_actions") or []
    return record


def build_target_evidence_bundle(
    *,
    project: str,
    run_id: str,
    now: str,
    fr_catalog_path: str | None,
    report_dir: Path,
    health_records: list[dict],
) -> dict | None:
    if not fr_catalog_path:
        return None
    try:
        from load_fr_catalog import load_fr_catalog
        catalog = load_fr_catalog(Path(fr_catalog_path))
    except Exception:
        return None

    junit_index = junit_records(report_dir / "reports" / "junit.xml")
    health_by_name = {record.get("name"): record for record in health_records}
    scanner_by_name = {scanner["name"]: scanner for scanner in LEVEL1_SCANNERS + LEVEL2_SCANNERS}
    evidence: list[dict] = []

    for tbt in catalog.tbts:
        tbt_id = tbt.get("id", "")
        tbt_type = tbt.get("type", "test")
        record = _junit_record_for_tbt(tbt, junit_index)
        if tbt_type in {"unit", "integration", "e2e", "load"}:
            status = record.get("status") if record else "missing"
            locator = (
                f"{record.get('classname', '')}::{record.get('name', '')}".strip(":")
                if record else (tbt.get("ref") or tbt_id)
            )
            artifact = _artifact_ref(report_dir, "reports/junit.xml", fmt="junit", locator=locator)
            test_inputs = [
                        _artifact_ref(
                            report_dir,
                            "generated-tests/VG_TEST_FRAMEWORK/manifest.json",
                            fmt="json",
                            schema_ref=SCHEMA_REFS["assurance_test_pack"],
                        )
                    ]
            tbt_ref_path = str(tbt.get("ref") or "").split("::", 1)[0]
            if tbt_ref_path.endswith((".js", ".ts", ".jsx", ".tsx", ".py")):
                test_inputs.append({"path": tbt_ref_path, "format": "test_source", "schema_ref": SCHEMA_REFS["test_source"]})
            ev = {
                "id": _safe_evidence_id(tbt_id),
                "type": "test_result",
                "result_status": status,
                "produced_by": tbt_id,
                "source": "reports/junit.xml",
                "source_locator": locator,
                "artifact": artifact,
                "raw_artifacts": [artifact],
                "test_actions": _test_actions_for_record(record, tbt, status, locator),
                "provenance": _provenance(
                    collector="VG_TEST_FRAMEWORK",
                    collected_at=now,
                    output_artifacts=[artifact],
                    tool=tbt.get("runner") or "test-runner",
                    input_artifacts=test_inputs,
                ),
            }
            if record:
                ev["observed"] = True
                ev["evidence_strength"] = "not_sufficient" if status == "execution_error" else "strong"
            if record and (record.get("message") or record.get("diagnostic") or status == "execution_error"):
                ev["metadata"] = {
                    "message": record.get("diagnostic") or record.get("message") or "",
                    "failure_kind": "harness_or_runner" if status == "execution_error" else "assertion_or_conformance",
                }
            evidence.append(ev)
        elif tbt_type == "scanner":
            scanner, _, rule = (tbt.get("ref") or "").partition(":")
            health = health_by_name.get(scanner) or {}
            health_status = health.get("status")
            scanner_def = scanner_by_name.get(scanner) or {}
            source = scanner_def.get("output")
            source = source if source else (f"reports/{scanner}.json" if scanner else "evidence-manifest.json")
            locator = rule or scanner or tbt_id
            artifact = _artifact_ref(
                report_dir,
                source,
                fmt=scanner_def.get("format"),
                locator=locator,
            )
            status = "missing"
            if health_status in {"PASS", "WARN"}:
                status = "passed"
            elif health_status == "FAIL":
                status = "failed"
            evidence.append({
                "id": _safe_evidence_id(tbt_id),
                "type": "scanner_result",
                "result_status": status,
                "produced_by": tbt_id,
                "source": source,
                "source_locator": locator,
                "artifact": artifact,
                "raw_artifacts": [artifact],
                "tool": scanner,
                "run_id": run_id,
                "provenance": _provenance(
                    collector="assurance-scan",
                    collected_at=now,
                    output_artifacts=[artifact],
                    tool=scanner,
                    container_image=scanner_def.get("image"),
                    normalizer=f"assurance-scan.{scanner_def.get('format')}" if scanner_def.get("format") else None,
                ),
                "metadata": {"scanner_health": health_status or "missing"},
            })
        else:
            artifact = _artifact_ref(report_dir, "manual-evidence-required.md", fmt="markdown", locator=tbt.get("ref") or tbt_id)
            evidence.append({
                "id": _safe_evidence_id(tbt_id),
                "type": "manual_note",
                "result_status": "manual_review",
                "produced_by": tbt_id,
                "source": "manual-evidence-required.md",
                "source_locator": tbt.get("ref") or tbt_id,
                "artifact": artifact,
                "raw_artifacts": [artifact],
                "reviewer": "unassigned",
                "provenance": _provenance(
                    collector="manual-evidence-template",
                    collected_at=now,
                    output_artifacts=[artifact],
                ),
            })

    evidence = [_enrich_evidence_io(record) for record in evidence]

    return {
        "schema_version": 1,
        "project": project,
        "generated_at": now,
        "evidence": evidence,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-dir", required=True)
    ap.add_argument("--target-dir", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--image-name", action="append", default=[])
    ap.add_argument("--target-url", action="append", default=[])
    ap.add_argument("--uploads-dir", action="append", default=[])
    ap.add_argument("--fr-catalog")
    args = ap.parse_args()

    report_dir = Path(args.report_dir)
    reports_subdir = report_dir / "reports"
    sbom_subdir = report_dir / "sbom"
    generated_tests_subdir = report_dir / "generated-tests"
    hashes_subdir = report_dir / "hashes"
    hashes_subdir.mkdir(parents=True, exist_ok=True)

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    config_status = load_json(report_dir / "config-status.json") or {"checks": []}
    test_inventory = load_json(reports_subdir / "test-inventory.json") or {}
    assurance_pack = load_json(generated_tests_subdir / "VG_TEST_FRAMEWORK" / "manifest.json") or {}
    junit = junit_summary(reports_subdir / "junit.xml")

    # Merge pre-recorded SKIPPED entries (from run-local.sh) with live classification.
    pre_recorded = load_json(report_dir / "scanner-health.json") or {"scanners": []}
    pre_recorded_by_name = {s["name"]: s for s in pre_recorded.get("scanners", [])}

    # Determine which Level-2 scanners should be SKIPPED based on flags.
    image_names = [v for v in args.image_name if v]
    target_urls = [v for v in args.target_url if v]
    uploads_dirs = [v for v in args.uploads_dir if v]
    requested_flags = {
        "image":   bool(image_names),
        "url":     bool(target_urls),
        "https":   any(url.startswith("https://") for url in target_urls),
        "uploads": bool(uploads_dirs),
    }

    all_scanners = LEVEL1_SCANNERS + LEVEL2_SCANNERS
    health_records = []
    findings_summary = {}

    for scanner in all_scanners:
        name = scanner["name"]
        # If pre-recorded as SKIPPED, keep it.
        if pre_recorded_by_name.get(name, {}).get("status") == "SKIPPED":
            health_records.append({
                "name": name,
                "level": scanner["level"],
                "image": scanner["image"],
                "status": "SKIPPED",
                "reason": pre_recorded_by_name[name].get("reason", "Not requested"),
            })
            continue

        # Level-2 scanners not requested via flag → SKIPPED.
        if scanner["level"] == 2:
            flag = scanner.get("flag")
            if flag and not requested_flags.get(flag):
                health_records.append({
                    "name": name,
                    "level": 2,
                    "image": scanner["image"],
                    "status": "SKIPPED",
                    "reason": f"--{flag} not supplied",
                })
                continue

        # Otherwise classify based on output file.
        status, reason = classify_health(scanner, report_dir, config_status)
        health_records.append({
            "name": name,
            "level": scanner["level"],
            "image": scanner["image"],
            "status": status,
            "reason": reason,
        })

        # Build findings summary entry, aggregating repeated target outputs.
        output_paths = output_candidates(scanner, report_dir)
        if scanner["name"] == "semgrep":
            findings_summary["semgrep"] = sum(count_semgrep(path) for path in output_paths)
        elif scanner["name"] == "gitleaks":
            totals = [count_gitleaks(path) for path in output_paths]
            findings_summary["gitleaks"] = sum(item[0] for item in totals)
        elif scanner["name"] in ("trivy-fs", "trivy-config", "trivy-image"):
            findings_summary[scanner["name"]] = add_counts([count_trivy(path) for path in output_paths])
        elif scanner["name"] in ("grype", "grype-image"):
            findings_summary[scanner["name"]] = add_counts([count_grype(path) for path in output_paths])
        elif scanner["name"] == "osv-scanner":
            findings_summary["osv_scanner"] = add_counts([count_osv(path) for path in output_paths])
        elif scanner["name"] in ("syft", "syft-image"):
            findings_summary[scanner["name"]] = sum(count_cyclonedx_components(path) for path in output_paths)
        elif scanner["name"] == "zap-baseline":
            findings_summary["zap"] = add_counts([count_zap(path) for path in output_paths])
        elif scanner["name"] == "testssl":
            findings_summary["testssl"] = add_counts([count_testssl(path) for path in output_paths])
        elif scanner["name"] == "security-headers":
            findings_summary["security_headers"] = add_counts([count_security_headers(path) for path in output_paths])
        elif scanner["name"] == "clamav":
            findings_summary["clamav"] = sum(count_clamav(path) for path in output_paths)

    # ----- Formulas ----------------------------------------------------------
    attempted = [r for r in health_records if r["status"] in ("PASS", "WARN", "FAIL")]
    n_pass = sum(1 for r in attempted if r["status"] == "PASS")
    n_warn = sum(1 for r in attempted if r["status"] == "WARN")
    n_fail = sum(1 for r in attempted if r["status"] == "FAIL")
    passed_ratio = (n_pass + 0.5 * n_warn) / max(1, len(attempted))
    automated_pct = round(100 * passed_ratio)

    # Manual coverage from manual-evidence-required.md (count non-PENDING items)
    # The template renders Status as `- **Status:** PENDING` so the regex must
    # tolerate markdown emphasis.
    manual_path = report_dir / "manual-evidence-required.md"
    total_manual = 14
    completed_manual = 0
    if manual_path.exists():
        text = manual_path.read_text(errors="replace")
        pending = len(re.findall(r"\*\*Status:\*\*\s*PENDING", text))
        completed_manual = max(0, total_manual - pending)
    manual_ratio = completed_manual / total_manual

    asvs_pct = round(100 * (0.7 * passed_ratio + 0.3 * manual_ratio))

    # Critical findings across all reports
    n_critical = 0
    for r in health_records:
        if r["status"] != "FAIL":
            continue
        # Approximate: count CRITICAL entries in findings_summary
        name = r["name"]
        if name in ("trivy-fs", "trivy-config", "trivy-image"):
            n_critical += findings_summary.get(name, {}).get("CRITICAL", 0)
        elif name in ("grype", "grype-image"):
            n_critical += findings_summary.get(name, {}).get("CRITICAL", 0)
        elif name == "osv-scanner":
            n_critical += findings_summary.get("osv_scanner", {}).get("CRITICAL", 0)
        elif name == "zap-baseline":
            n_critical += findings_summary.get("zap", {}).get("CRITICAL", 0)
        elif name == "testssl":
            n_critical += findings_summary.get("testssl", {}).get("CRITICAL", 0)
        elif name == "security-headers":
            n_critical += findings_summary.get("security_headers", {}).get("CRITICAL", 0)
        elif name == "gitleaks":
            n_critical += findings_summary.get("gitleaks", 0)

    gitleaks_high = findings_summary.get("gitleaks", 0)
    level1_ok = all(
        r["status"] in ("PASS", "WARN") for r in health_records if r["level"] == 1
    )
    ready = (
        n_critical == 0
        and gitleaks_high == 0
        and automated_pct >= 90
        and level1_ok
    )
    release_recommendation = "READY" if ready else "NOT READY"

    existing_manifest = {}
    try:
        manifest_path = report_dir / "evidence-manifest.json"
        if manifest_path.exists() and manifest_path.stat().st_size > 0:
            existing_manifest = json.loads(manifest_path.read_text(errors="replace"))
    except Exception:
        existing_manifest = {}

    source_repo = (
        os.environ.get("ASSURANCE_SCAN_SOURCE_REPO")
        or existing_manifest.get("source_repo")
        or None
    )
    repository_name = (
        os.environ.get("ASSURANCE_SCAN_REPOSITORY_NAME")
        or existing_manifest.get("repository")
        or get_git_repo_name(source_repo)
        or get_git_repo_name(args.target_dir)
    )
    original_branch = (
        os.environ.get("ASSURANCE_SCAN_ORIGINAL_BRANCH")
        or existing_manifest.get("git_branch")
        or get_git_branch(source_repo)
        or get_git_branch(args.target_dir)
    )
    safe_scan_branch = (
        os.environ.get("ASSURANCE_SCAN_SAFE_SCAN_BRANCH")
        or existing_manifest.get("safe_scan_branch")
        or None
    )
    git_commit = get_git_commit(args.target_dir) or existing_manifest.get("git_commit")

    target_evidence_bundle = build_target_evidence_bundle(
        project=Path(args.target_dir).name or "target-project",
        run_id=args.run_id,
        now=now,
        fr_catalog_path=args.fr_catalog,
        report_dir=report_dir,
        health_records=health_records,
    )
    if target_evidence_bundle is not None:
        (report_dir / "evidence-bundle.json").write_text(json.dumps(target_evidence_bundle, indent=2))

    # Keep the standalone scanner-health artifact in sync with the merged
    # records that also flow into evidence-manifest.json.
    (report_dir / "scanner-health.json").write_text(
        json.dumps(
            {
                "scanners": [
                    {
                        "name": r["name"],
                        "level": r["level"],
                        "image": r["image"],
                        "status": r["status"],
                        "reason": r["reason"],
                    }
                    for r in health_records
                ]
            },
            indent=2,
        )
        + "\n"
    )

    # ----- Compute hashes for every evidence artifact ------------------------
    hashed_files = []
    hash_roots = [reports_subdir, sbom_subdir, generated_tests_subdir]
    root_level_artifacts = [
        report_dir / "evidence-bundle.json",
        report_dir / "manual-evidence-required.md",
        report_dir / "config-status.json",
        report_dir / "scanner-health.json",
    ]
    for sub in hash_roots:
        if not sub.is_dir():
            continue
        for f in sorted(sub.rglob("*")):
            if not f.is_file():
                continue
            digest = file_sha256(f)
            rel = f.relative_to(report_dir)
            write_hash_sidecar(report_dir, f)
            hashed_files.append({
                "file": str(rel),
                "bytes": f.stat().st_size,
                "sha256": digest,
            })
    for f in root_level_artifacts:
        if not f.is_file():
            continue
        digest = file_sha256(f)
        rel = f.relative_to(report_dir)
        write_hash_sidecar(report_dir, f)
        hashed_files.append({
            "file": str(rel),
            "bytes": f.stat().st_size,
            "sha256": digest,
        })

    # ----- Write evidence-manifest.json --------------------------------------
    manifest = {
        "project": "Assurance Scan",
        "run_id": args.run_id,
        "generated_at": now,
        "target_dir": args.target_dir,
        "source_repo": source_repo,
        "repository": repository_name,
        "git_branch": original_branch,
        "safe_scan_branch": safe_scan_branch,
        "git_commit": git_commit,
        "image_scanned": image_names or None,
        "url_scanned": target_urls or None,
        "uploads_scanned": uploads_dirs or None,
        "tools": {r["name"]: {"image": r["image"], "level": r["level"]} for r in health_records},
        "scanner_health": {r["name"]: {"status": r["status"], "reason": r["reason"]} for r in health_records},
        "findings_summary": findings_summary,
        "test_evidence": {
            "inventory": test_inventory.get("summary") or {"files": 0, "cases": 0, "by_type": {}},
            "junit": junit,
        },
        "assurance_test_pack": {
            "present": bool(assurance_pack),
            "mode": assurance_pack.get("mode"),
            "path": "generated-tests/VG_TEST_FRAMEWORK/manifest.json" if assurance_pack else None,
            "summary": assurance_pack.get("summary") or {},
            "safety_policy": assurance_pack.get("safety_policy") or {},
        },
        "evidence_files": hashed_files,
        "assurance": {
            "automated_assurance_pct": automated_pct,
            "asvs_traceability_pct": asvs_pct,
            "release_recommendation": release_recommendation,
            "attempted_scanners": len(attempted),
            "passed": n_pass,
            "warned": n_warn,
            "failed": n_fail,
            "skipped": sum(1 for r in health_records if r["status"] == "SKIPPED"),
            "critical_findings": n_critical,
            "manual_items_total": total_manual,
            "manual_items_completed": completed_manual,
        },
        "disclaimer": (
            "This evidence bundle demonstrates the automated local and runtime security "
            "assurance activities completed against the scanned version of the target application. "
            "Environment-specific controls and manual evidence remain necessary to "
            "satisfy the full ASVS Traceability Matrix."
        ),
    }
    (report_dir / "evidence-manifest.json").write_text(json.dumps(manifest, indent=2))

    # ----- Write executive-summary.md ----------------------------------------
    md = []
    md.append("# ASVS Security Scan — Executive Summary")
    md.append("")
    md.append(f"- **Project scanned:** `{args.target_dir}`")
    md.append(f"- **Run ID:** `{args.run_id}`")
    md.append(f"- **Timestamp:** `{now}`")
    md.append(f"- **Git commit:** `{git_commit or 'not available'}`")
    md.append(f"- **Images scanned:** `{', '.join(image_names) if image_names else '—'}`")
    md.append(f"- **URLs scanned:** `{', '.join(target_urls) if target_urls else '—'}`")
    md.append(f"- **Uploads scanned:** `{', '.join(uploads_dirs) if uploads_dirs else '—'}`")
    md.append("")
    md.append("## Scanner health")
    md.append("")
    md.append("| Scanner | Level | Status | Reason |")
    md.append("|---|---:|---|---|")
    for r in health_records:
        md.append(f"| {r['name']} | L{r['level']} | `{r['status']}` | {r['reason']} |")
    md.append("")
    md.append("## Findings summary")
    md.append("")
    md.append("| Scanner | Findings |")
    md.append("|---|---|")
    for k, v in findings_summary.items():
        if isinstance(v, dict):
            md.append(f"| {k} | {fmt_counts(v)} |")
        else:
            md.append(f"| {k} | {v} |")
    md.append("")
    md.append("## Reports generated")
    md.append("")
    for h in hashed_files:
        md.append(f"- `{h['file']}` — `{h['sha256'][:16]}…` ({h['bytes']:,} bytes)")
    md.append("")
    md.append("## Manual evidence required")
    md.append("")
    md.append(f"See `manual-evidence-required.md` for the full {total_manual}-item checklist. "
              f"{total_manual - completed_manual} items still PENDING.")
    md.append("")
    md.append("## Overall automated assurance")
    md.append("")
    md.append(f"- **Automated assurance:** `{automated_pct}%`")
    md.append(f"- **ASVS Traceability (coverage-based estimate):** `{asvs_pct}%`")
    md.append(f"- **Release recommendation:** **`{release_recommendation}`**")
    md.append(f"- Critical findings: `{n_critical}`")
    md.append(f"- Gitleaks findings: `{gitleaks_high}`")
    md.append("")
    md.append("## Disclaimer")
    md.append("")
    md.append(f"> {manifest['disclaimer']}")
    md.append("")
    (report_dir / "executive-summary.md").write_text("\n".join(md))

    # ----- Write scanner-run-summary.txt -------------------------------------
    lines = []
    lines.append("=" * 70)
    lines.append("ASVS SECURITY SCANNER — SCANNER RUN SUMMARY")
    lines.append("=" * 70)
    lines.append(f"Run ID:        {args.run_id}")
    lines.append(f"Target:        {args.target_dir}")
    lines.append(f"Git commit:    {git_commit or 'n/a'}")
    for image in image_names:
        lines.append(f"Image scanned: {image}")
    for url in target_urls:
        lines.append(f"URL scanned:   {url}")
    for uploads in uploads_dirs:
        lines.append(f"Uploads:       {uploads}")
    lines.append("")
    lines.append("Scanner health:")
    for r in health_records:
        lines.append(f"  {r['status']:<8} {r['name']:<22} {r['reason']}")
    lines.append("")
    lines.append(f"Attempted: {len(attempted)}  Passed: {n_pass}  Warned: {n_warn}  Failed: {n_fail}  Skipped: {manifest['assurance']['skipped']}")
    lines.append(f"Critical findings: {n_critical}")
    lines.append(f"Automated assurance: {automated_pct}%")
    lines.append(f"ASVS Traceability (coverage-based): {asvs_pct}%")
    lines.append(f"Release recommendation: {release_recommendation}")
    lines.append("")
    if release_recommendation != "READY":
        lines.append("Outstanding work:")
        for r in health_records:
            if r["status"] == "FAIL":
                lines.append(f"  - Fix {r['name']}: {r['reason']}")
        for r in health_records:
            if r["status"] == "SKIPPED":
                lines.append(f"  - Run optional scanner {r['name']} ({r['reason']})")
        lines.append(f"  - Complete {total_manual - completed_manual} manual-evidence items")
        lines.append(f"  - Validate audit logging, run pen-test, etc. (see manual-evidence-required.md)")
    lines.append("=" * 70)
    (report_dir / "scanner-run-summary.txt").write_text("\n".join(lines) + "\n")

    print(f"evidence bundle written to: {report_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
