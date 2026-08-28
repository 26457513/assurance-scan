#!/usr/bin/env python3
"""Framework compliance tab renderer with traffic lights."""
from __future__ import annotations

import html
import re
from defusedxml import ElementTree as ET
from pathlib import Path
from typing import Any

from generate_dashboard import (
    load_json,
    manual_evidence_items,
    short_text,
    sev_badge,
    output_candidates,
)

# Ruleset tabs (ASVS / NIST / etc. with traffic lights)
# ===========================================================================

# Map ruleset name (as used in fr-catalog scope) -> canonical snapshot path + display name
RULESET_SNAPSHOTS = {
    "ASVS": ("rulesets/asvs/5.0.0.json", "ASVS"),
    "NIST-800-53": ("rulesets/nist-800-53/5.2.0.json", "NIST 800-53"),
}

ASVS_CHAPTER_NAMES = {
    "V1": "Encoding and Injection Prevention",
    "V2": "Authentication",
    "V3": "Session Management",
    "V4": "Access Control",
    "V5": "Validation, Sanitization and Encoding",
    "V6": "Stored Cryptography",
    "V7": "Error Handling and Logging",
    "V8": "Data Protection",
    "V9": "Communications",
    "V10": "Malicious Code",
    "V11": "Business Logic",
    "V12": "File and Resources",
    "V13": "API and Web Service",
    "V14": "Configuration",
    "V15": "Requirements",
    "V16": "Architecture",
    "V17": "Supply Chain",
}


def _framework_requirements(framework: str) -> list[dict]:
    """Load ruleset rows from bundled canonical snapshot."""
    spec = RULESET_SNAPSHOTS.get(framework)
    if not spec:
        return []
    rel_path, _ = spec
    path = Path(__file__).resolve().parent.parent.parent / "resources" / rel_path
    if not path.exists():
        return []
    data = load_json(path) or {}
    return data.get("rows") or []


def _scanner_findings_for_rule(scanner: str, pattern: str, report_dir: Path) -> list[dict]:
    """Find scanner findings whose rule_id matches the pattern (fnmatch)."""
    import fnmatch
    matched: list[dict] = []
    if scanner == "semgrep":
        sarif = load_json(report_dir / "reports" / "semgrep.sarif") or {}
        for run in sarif.get("runs", []) or []:
            for result in run.get("results", []) or []:
                rid = result.get("ruleId", "")
                if fnmatch.fnmatch(rid, pattern):
                    loc = (result.get("locations") or [{}])[0].get("physicalLocation") or {}
                    artifact = (loc.get("artifactLocation") or {}).get("uri", "-")
                    line = (loc.get("region") or {}).get("startLine")
                    matched.append({
                        "rule_id": rid, "severity": "WARNING",
                        "location": f"{artifact}:{line}" if line else artifact,
                        "message": (result.get("message") or {}).get("text", ""),
                    })
    elif scanner == "gitleaks":
        data = load_json(report_dir / "reports" / "gitleaks.json")
        if isinstance(data, list):
            for f in data:
                rid = f.get("RuleID", "")
                if fnmatch.fnmatch(rid, pattern):
                    matched.append({
                        "rule_id": rid, "severity": "HIGH",
                        "location": f"{f.get('File', '-')}:{f.get('StartLine', '')}",
                        "message": f.get("Description", ""),
                    })
    elif scanner in ("trivy-vuln", "trivy-config", "trivy-secret"):
        result_key = {"trivy-vuln": "Vulnerabilities", "trivy-config": "Misconfigurations", "trivy-secret": "Secrets"}[scanner]
        id_field = {"trivy-vuln": "VulnerabilityID", "trivy-config": "ID", "trivy-secret": "RuleID"}[scanner]
        for rel in ("reports/trivy-fs.json", "reports/trivy-config.json"):
            data = load_json(report_dir / rel) or {}
            for result in data.get("Results", []) or []:
                target = result.get("Target", "-")
                for item in result.get(result_key, []) or []:
                    if scanner == "trivy-config" and item.get("Status") and item.get("Status") != "FAIL":
                        continue
                    rid = item.get(id_field, "")
                    if fnmatch.fnmatch(rid, pattern):
                        matched.append({
                            "rule_id": rid,
                            "severity": str(item.get("Severity", "UNKNOWN")).upper(),
                            "location": target,
                            "message": item.get("Title", item.get("Message", "")),
                        })
    elif scanner == "grype":
        for path in output_candidates(report_dir, "reports/grype.json", include_suffixed=True):
            data = load_json(path) or {}
            for m in data.get("matches", []) or []:
                vuln = m.get("vulnerability") or {}
                rid = vuln.get("id", "")
                if fnmatch.fnmatch(rid, pattern):
                    artifact = m.get("artifact") or {}
                    matched.append({
                        "rule_id": rid,
                        "severity": str(vuln.get("severity", "UNKNOWN")).upper(),
                        "location": f"{artifact.get('name', '-')} {artifact.get('version', '')}".strip(),
                        "message": vuln.get("description", ""),
                    })
    return matched


def _scanner_execution_evidence(scanner: str, pattern: str, report_dir: Path) -> dict | None:
    """Return positive scanner-run evidence for a mapped scanner rule/pattern."""
    import fnmatch

    manifest = load_json(report_dir / "evidence-manifest.json") or {}
    health = (manifest.get("scanner_health") or {}).get(scanner)
    scanner_to_output = {
        "semgrep": report_dir / "reports" / "semgrep.sarif",
        "gitleaks": report_dir / "reports" / "gitleaks.json",
        "trivy-vuln": report_dir / "reports" / "trivy-fs.json",
        "trivy-config": report_dir / "reports" / "trivy-config.json",
        "trivy-secret": report_dir / "reports" / "trivy-fs.json",
        "grype": report_dir / "reports" / "grype.json",
    }
    output = scanner_to_output.get(scanner)
    if not output or not output.exists():
        return None
    if health and health.get("status") == "SKIPPED":
        return None
    if scanner == "semgrep":
        sarif = load_json(output) or {}
        rules: set[str] = set()
        for run in sarif.get("runs", []) or []:
            driver = ((run.get("tool") or {}).get("driver") or {})
            for rule in driver.get("rules", []) or []:
                rid = rule.get("id") or rule.get("name")
                if rid:
                    rules.add(rid)
        if rules and not any(fnmatch.fnmatch(rule, pattern) for rule in rules):
            return None
    return {
        "scanner": scanner,
        "rule_id": pattern,
        "severity": "INFO",
        "location": str(output.relative_to(report_dir)),
        "message": f"{scanner} executed for mapped rule/pattern {pattern} and no matching finding was reported.",
    }


def _target_dir_from_manifest(report_dir: Path) -> Path | None:
    manifest = load_json(report_dir / "evidence-manifest.json") or {}
    target_dir = manifest.get("target_dir")
    return Path(target_dir) if target_dir else None


def _load_test_inventory(report_dir: Path) -> dict[str, dict]:
    data = load_json(report_dir / "reports" / "test-inventory.json") or {}
    index: dict[str, dict] = {}
    for item in data.get("files", []) or []:
        path = item.get("path", "")
        if not path:
            continue
        index[path] = item
        index[Path(path).name] = item
        for case in item.get("cases", []) or []:
            ref = case.get("ref", "")
            name = case.get("name", "")
            record = {**item, "case": case}
            if ref:
                index[ref] = record
            if name:
                index[name] = record
                index[f"{path}::{name}"] = record
    return index


def _junit_paths(report_dir: Path, junit_xml_path: str | None = None) -> list[Path]:
    paths: list[Path] = []
    if junit_xml_path:
        for part in str(junit_xml_path).split(":"):
            if part:
                paths.append(Path(part))
    for candidate in [
        report_dir / "junit.xml",
        report_dir / "reports" / "junit.xml",
        report_dir / "test-results.xml",
        report_dir / "reports" / "test-results.xml",
    ]:
        paths.append(candidate)
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved not in seen and path.exists():
            seen.add(resolved)
            out.append(path)
    return out


def _xml_attrs(text: str) -> dict[str, str]:
    return {
        str(match.group(1)): str(match.group(2) or match.group(3) or "")
        for match in re.finditer(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""", text)
    }


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
            status = "failed" if failure is not None or error is not None else "skipped" if skipped is not None else "passed"
            elem = failure or error or skipped
            cases.append({
                "name": case.get("name") or "",
                "classname": case.get("classname") or "",
                "file": case.get("file") or "",
                "status": status,
                "message": (elem.get("message") if elem is not None else "") or "",
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
                status = "skipped"
            else:
                status = "passed"
            message_match = re.search(r"<(?:failure|error|skipped)\b([^>]*)", body, re.IGNORECASE)
            message = _xml_attrs(message_match.group(1)).get("message", "") if message_match else ""
            cases.append({
                "name": attrs.get("name", ""),
                "classname": attrs.get("classname", ""),
                "file": attrs.get("file", ""),
                "status": status,
                "message": message,
            })
        return cases


def _load_junit_index(report_dir: Path, junit_xml_path: str | None = None) -> dict[str, dict]:
    """Return lookup data for JUnit testcase refs.

    Keys include testcase name, classname.name and file::name variants so FR
    refs can use either a plain test name or a path-qualified reference.
    """
    index: dict[str, dict] = {}
    for path in _junit_paths(report_dir, junit_xml_path):
        for case in _junit_case_records(path):
            name = case.get("name") or ""
            classname = case.get("classname") or ""
            file_attr = case.get("file") or ""
            status = case.get("status") or "passed"
            message = case.get("message") or ""
            record = {
                "status": status,
                "name": name,
                "classname": classname,
                "file": file_attr,
                "source": str(path),
                "message": message,
            }
            keys = {name, f"{classname}.{name}" if classname and name else "", f"{classname}::{name}" if classname and name else ""}
            if file_attr and name:
                keys.add(f"{file_attr}::{name}")
            for key in keys:
                if key:
                    index[key] = record
    return index


def _test_record_for_ref(ref: str, test_index: dict[str, dict]) -> dict | None:
    if ref in test_index:
        return test_index[ref]
    if "::" in ref:
        path, _, name = ref.partition("::")
        if ref in test_index:
            return test_index[ref]
        if name in test_index:
            return test_index[name]
        basename_key = f"{Path(path).name}::{name}"
        if basename_key in test_index:
            return test_index[basename_key]
        for key, record in test_index.items():
            if key.endswith(f"::{name}") or key.endswith(f".{name}"):
                return record
    return None


def _discovered_test_for_ref(ref: str, inventory_index: dict[str, dict]) -> dict | None:
    if ref in inventory_index:
        return inventory_index[ref]
    if "::" in ref:
        path, _, name = ref.partition("::")
        candidates = [ref, path, Path(path).name, name]
        for candidate in candidates:
            if candidate in inventory_index:
                return inventory_index[candidate]
        for key, record in inventory_index.items():
            if key.endswith(f"::{name}") or key.endswith(path) or key.endswith(Path(path).name):
                return record
    return None


def _manual_evidence_exists(ref: str, report_dir: Path) -> bool:
    path = Path(ref)
    target_dir = _target_dir_from_manifest(report_dir)
    candidates = [
        path if path.is_absolute() else report_dir / path,
        path if path.is_absolute() else report_dir / "reports" / path,
    ]
    if target_dir and not path.is_absolute():
        candidates.append(target_dir / path)
    return any(candidate.exists() for candidate in candidates)


def _compute_fr_evidence_status(
    fr: dict,
    tbts: list[dict],
    report_dir: Path,
    test_index: dict[str, dict] | None = None,
    inventory_index: dict[str, dict] | None = None,
) -> tuple[str, list[dict]]:
    """Return (status, failing_evidence) for one FR.

    status: 'passed' | 'partial' | 'failed' | 'missing'
    failing_evidence: list of dicts with scanner/rule/location/message
    """
    failing: list[dict] = []
    has_any_evidence = False
    has_declared_manual = False
    missing_evidence: list[dict] = []
    test_index = test_index or {}
    inventory_index = inventory_index or {}
    for tbt in tbts:
        vtype = tbt.get("type", "test")
        ref = tbt.get("ref") or tbt.get("id", "")
        tbt_id = tbt.get("id") or ref or "tbt"
        if vtype == "scanner":
            # Parse 'scanner_name:pattern'
            if ":" not in ref:
                continue
            scanner, pattern = ref.split(":", 1)
            findings = _scanner_findings_for_rule(scanner, pattern, report_dir)
            if findings:
                for f in findings:
                    f["scanner"] = scanner
                    failing.append(f)
            elif _scanner_execution_evidence(scanner, pattern, report_dir):
                has_any_evidence = True
            else:
                missing_evidence.append({
                    "scanner": scanner,
                    "rule_id": pattern,
                    "severity": "INFO",
                    "location": "scanner execution evidence",
                    "message": f"No scanner execution evidence was found for mapped scanner rule/pattern {ref}.",
                })
        elif vtype in ("unit", "integration", "e2e", "load", "test"):
            record = _test_record_for_ref(ref, test_index)
            if not record:
                discovered = _discovered_test_for_ref(ref, inventory_index)
                if discovered:
                    missing_evidence.append({
                        "scanner": vtype,
                        "rule_id": tbt_id,
                        "severity": "INFO",
                        "location": discovered.get("path", "reports/test-inventory.json"),
                        "message": "Project test was discovered, but no exported JUnit result proved that it ran and passed.",
                    })
                else:
                    missing_evidence.append({
                        "scanner": vtype,
                        "rule_id": tbt_id,
                        "severity": "INFO",
                        "location": "JUnit/test evidence",
                        "message": "A declared project test or TBT test basis has no matching discovered test or exported test result.",
                    })
                continue
            has_any_evidence = True
            if record.get("status") != "passed":
                failing.append({
                    "scanner": vtype,
                    "rule_id": ref,
                    "severity": "HIGH" if record.get("status") == "failed" else "WARNING",
                    "location": record.get("source", "junit"),
                    "message": record.get("message") or f"JUnit testcase status: {record.get('status')}",
                })
    for ev in fr.get("evidence") or []:
        ev_type = ev.get("type")
        ref = ev.get("ref", "")
        if ev_type in ("manual", "screenshot"):
            has_declared_manual = True
            if _manual_evidence_exists(ref, report_dir) or ev.get("status") == "manual":
                has_any_evidence = True
        elif ev_type in ("scanner", "test"):
            # Scanner/test evidence is normally represented through TBT records.
            has_any_evidence = True
    if failing:
        return "failed", failing
    if has_any_evidence and missing_evidence:
        return "partial", missing_evidence[:5]
    if has_any_evidence:
        return "passed", []
    if missing_evidence:
        return "missing", missing_evidence[:5]
    if has_declared_manual:
        return "missing", [{
            "scanner": "manual",
            "rule_id": "manual-evidence",
            "severity": "INFO",
            "location": "FR catalog",
            "message": "Manual evidence is declared but no matching artifact was found in the scan bundle.",
        }]
    return "missing", []


def _tbts_by_fr(fr_catalog: Any) -> dict[str, list[dict]]:
    by_fr: dict[str, list[dict]] = {}
    for tbt in getattr(fr_catalog, "tbts", []) or []:
        for fr_id in tbt.get("proves") or []:
            by_fr.setdefault(fr_id, []).append(tbt)
    return by_fr


def _tbts_by_compliance_row(fr_catalog: Any) -> dict[tuple[str, str], list[dict]]:
    by_row: dict[tuple[str, str], list[dict]] = {}
    for tbt in getattr(fr_catalog, "tbts", []) or []:
        for row in tbt.get("compliance") or []:
            ruleset = row.get("ruleset", "")
            row_id = row.get("row", "")
            if ruleset and row_id:
                by_row.setdefault((ruleset, row_id), []).append(tbt)
    return by_row


def _compute_compliance_row_state(
    row_id: str,
    framework: str,
    fr_catalog: Any,
    tbt_evidence: dict[str, tuple[str, list[dict]]],
    tbts_for_row: dict[tuple[str, str], list[dict]],
) -> tuple[str, list[dict], list[str]]:
    """Return (state, culprit_findings, claiming_fr_ids).

    state: 'satisfied' | 'partial' | 'failed' | 'unaddressed' | 'na' | 'filtered'
    """
    # Check na_rows first (top-level project declaration)
    for na in fr_catalog.na_rows:
        if na.get("ruleset") == framework and na.get("row") == row_id:
            return "na", [], []

    mapped_tbts = tbts_for_row.get((framework, row_id), [])
    claiming_frs = list(dict.fromkeys(
        fr_id
        for tbt in mapped_tbts
        for fr_id in (tbt.get("proves") or [])
    ))

    if not claiming_frs:
        return "unaddressed", [], []

    # Aggregate evidence status across TBTs mapped to this row. A row is
    # satisfied only when every mapped TBT has passing evidence.
    all_culprits: list[dict] = []
    statuses: list[str] = []
    for tbt in mapped_tbts:
        tbt_id = tbt.get("id", "")
        status, culprits = tbt_evidence.get(tbt_id, ("missing", []))
        statuses.append(status)
        if status == "failed":
            for c in culprits:
                c["tbt_id"] = tbt_id
                all_culprits.append(c)
        elif status == "partial":
            for c in culprits:
                c["tbt_id"] = tbt_id
                all_culprits.append(c)

    if any(status == "failed" for status in statuses):
        return "failed", all_culprits, claiming_frs
    if statuses and all(status == "passed" for status in statuses):
        return "satisfied", [], claiming_frs
    if any(status in ("passed", "partial") for status in statuses):
        return "partial", all_culprits, claiming_frs
    return "unaddressed", [], claiming_frs  # all claiming FRs have missing evidence


def render_framework_tab(
    framework: str,
    fr_catalog: Any,
    report_dir: Path,
    junit_xml_path: str | None = None,
    assurance_status: dict[str, Any] | None = None,
    ruleset_projection: dict[str, Any] | None = None,
) -> str:
    """Render one framework tab (ASVS, NIST 800-53, etc.)."""
    rows = _framework_requirements(framework)
    if not rows:
        return (
            f'<section class="card"><div class="empty-state">'
            f'Ruleset snapshot for {html.escape(framework)} not bundled under data/rulesets. '
            f'Add a canonical ruleset.schema.json snapshot and rebuild.</div></section>'
        )

    # Apply scope filter
    scope_entry = fr_catalog.scope.get(framework) or {}
    levels = scope_entry.get("levels") or scope_entry.get("baselines") or scope_entry.get("saq") or scope_entry.get("tier")
    if levels:
        # Normalise scope levels to a comparable set.
        # ASVS levels come as integers (1, 2, 3) in the snapshot but strings ("L1", "L2") in scope.
        # NIST baselines come as strings in both places.
        levels_norm = set()
        for level in levels:
            s = str(level).upper().lstrip("L")
            levels_norm.add(s)          # "1", "2", "3" (numeric)
            levels_norm.add(f"L{s}")    # "L1", "L2", "L3" (prefixed)
            levels_norm.add(str(level).upper())  # original uppercase form
        in_scope_rows = []
        filtered_count = 0
        for row in rows:
            row_level = row.get("level")
            if row_level is not None:
                row_level_str = str(row_level).upper()
                row_level_norm = row_level_str.lstrip("L")
                in_scope = (row_level_str in levels_norm or
                            row_level_norm in levels_norm or
                            f"L{row_level_norm}" in levels_norm)
            else:
                # No level field (NIST baselines, etc.) — check other scope dimensions
                in_scope = True  # default to in-scope if no level field to filter on
            if in_scope:
                in_scope_rows.append((row, True))
            else:
                in_scope_rows.append((row, False))
                filtered_count += 1
    else:
        in_scope_rows = [(row, True) for row in rows]
        filtered_count = 0

    # Compute FR evidence status once per FR
    test_index = _load_junit_index(report_dir, junit_xml_path)
    inventory_index = _load_test_inventory(report_dir)
    tbts_for_fr = _tbts_by_fr(fr_catalog)
    tbts_for_row = _tbts_by_compliance_row(fr_catalog)
    fr_evidence: dict[str, tuple[str, list[dict]]] = {}
    for fr in getattr(fr_catalog, "frs", []) or []:
        fr_evidence[fr["id"]] = _compute_fr_evidence_status(
            fr,
            tbts_for_fr.get(fr["id"], []),
            report_dir,
            test_index,
            inventory_index,
        )
    tbt_evidence: dict[str, tuple[str, list[dict]]] = {}
    for tbt in getattr(fr_catalog, "tbts", []) or []:
        tbt_evidence[tbt.get("id", "")] = _compute_fr_evidence_status(
            {},
            [tbt],
            report_dir,
            test_index,
            inventory_index,
        )

    resolved_rows = _resolved_rows_for_framework(assurance_status, framework)

    projection_rows = {}
    if ruleset_projection:
        projection_rows = {
            str(item.get("row") or ""): item
            for item in ruleset_projection.get("rows") or []
            if item.get("row")
        }
    uses_graph_projection = bool(projection_rows)

    # Compute row states. When available, the runtime graph projection is the
    # source of truth for state and traceability; the bundled snapshot only
    # supplies stable row text and chapter metadata for display.
    state_counts = {"satisfied": 0, "partial": 0, "failed": 0, "unaddressed": 0, "na": 0, "filtered": filtered_count}
    row_states: list[tuple[dict, str, list[dict], list[str], bool, dict | None]] = []
    for row, in_scope in in_scope_rows:
        if not in_scope:
            row_states.append((row, "filtered", [], [], False, None))
            continue
        projected = projection_rows.get(row["id"])
        if projected:
            state = str(projected.get("ui_state") or _framework_state_from_resolved_status(str(projected.get("status") or "")))
            culprits = []
            claiming = [str(item) for item in projected.get("frs") or [] if item]
            resolved = {
                "status": projected.get("status", state),
                "reasons": projected.get("reasons") or [],
                "tbt_refs": projected.get("tbts") or [],
                "scanner_evidence": projected.get("scanner_evidence") or [],
                "scanner_blockers": projected.get("scanner_blockers") or [],
                "source": "runtime_graph",
            }
        else:
            state, culprits, claiming = _compute_compliance_row_state(
                row["id"], framework, fr_catalog, tbt_evidence, tbts_for_row
            )
            resolved = resolved_rows.get(row["id"])
            if resolved:
                state = _framework_state_from_resolved_status(resolved.get("status", state))
                if resolved.get("fr_refs"):
                    claiming = list(dict.fromkeys([*claiming, *resolved.get("fr_refs", [])]))
        state_counts[state] = state_counts.get(state, 0) + 1
        row_states.append((row, state, culprits, claiming, True, resolved))

    applicable = state_counts["satisfied"] + state_counts["partial"] + state_counts["failed"] + state_counts["unaddressed"] + state_counts["na"]
    coverage_pct = (state_counts["satisfied"] / applicable * 100) if applicable else 0
    manual_items = manual_evidence_items(report_dir) if framework == "ASVS" else []
    manual_total = len(manual_items)
    manual_done = sum(1 for item in manual_items if item.get("status") not in ("", "PENDING"))
    manual_pct = (manual_done / manual_total * 100) if manual_total else 100
    assurance_pct = round((0.7 * coverage_pct) + (0.3 * manual_pct))

    display_name = RULESET_SNAPSHOTS.get(framework, (None, framework))[1]
    selected_levels: set[str] = set()
    if levels:
        selected_levels = {f"L{str(level).upper().lstrip('L')}" for level in levels}
    scope_str = ", ".join(f"{k}: {','.join(v)}" for k, v in scope_entry.items()) if scope_entry else "all levels"
    scope_explain = ""
    if framework == "ASVS":
        level_counts: dict[str, int] = {}
        for row in rows:
            if row.get("level") is None:
                continue
            level = f"L{str(row.get('level')).upper().lstrip('L')}"
            level_counts[level] = level_counts.get(level, 0) + 1
        all_levels = sorted(
            level_counts.keys(),
            key=lambda value: int(value[1:]) if value[1:].isdigit() else 99,
        )
        if selected_levels:
            level_chips = "".join(
                f'<span class="fw-scope-chip {"is-in" if level in selected_levels else "is-out"}">'
                f'{html.escape(level)} <em>{"in scope" if level in selected_levels else "out of scope"}</em> '
                f'<b>{level_counts.get(level, 0)}</b></span>'
                for level in all_levels
            )
            scope_str = "selected levels: " + ", ".join(sorted(selected_levels, key=lambda value: int(value[1:]) if value[1:].isdigit() else 99))
            scope_explain = (
                f'<div class="fw-scope-explain">{level_chips}'
                f'<span class="fw-scope-note">Scope is read from the project FR catalog.</span></div>'
            )

    assurance_tile = ""
    if framework == "ASVS":
        assurance_tip = (
            "Combined ASVS assurance score.\n\n"
            f"Scan/evidence coverage: {coverage_pct:.0f}%\n"
            f"Manual completion: {manual_done}/{manual_total}\n\n"
            "Formula: 70% scan/evidence coverage + 30% manual-step completion."
        )
        assurance_tile = (
            f'<div class="metric fw-assurance-metric" data-regime-assurance-score="asvs" '
            f'data-auto-pct="{coverage_pct:.2f}" data-manual-total="{manual_total}" data-manual-done="{manual_done}" '
            f'data-tooltip="{html.escape(assurance_tip)}">'
            f'<b style="color:#56c7b7">{assurance_pct}%</b><span>ASVS assurance · 70% scan, 30% manual</span></div>'
        )

    metric_tips = {
        "satisfied": "In-scope compliance rows with a complete FR -> TBT/test -> passing evidence chain.",
        "partial": "In-scope compliance rows with some mapped FR/test/evidence coverage, but not enough to call the row satisfied.",
        "failed": "In-scope compliance rows with failing evidence, failed tests, or findings that contradict the requirement.",
        "unaddressed": "In-scope compliance rows with no sufficient mapped FR, test, or evidence chain yet.",
        "na": "In-scope compliance rows explicitly assessed as not applicable to this product/context.\n\nThis is not the same as out of scope. Out-of-scope rows are excluded by the selected level/profile, such as ASVS L3 when only L1/L2 are selected.",
    }

    tiles = (
        f'{assurance_tile}'
        f'<div class="metric" data-tooltip="{html.escape(metric_tips["satisfied"])}"><b style="color:#35d07f">{state_counts["satisfied"]}</b><span>Satisfied</span></div>'
        f'<div class="metric" data-tooltip="{html.escape(metric_tips["partial"])}"><b style="color:#8fcbe8">{state_counts["partial"]}</b><span>Partial</span></div>'
        f'<div class="metric" data-tooltip="{html.escape(metric_tips["failed"])}"><b style="color:#ff4d6d">{state_counts["failed"]}</b><span>Failed</span></div>'
        f'<div class="metric" data-tooltip="{html.escape(metric_tips["unaddressed"])}"><b style="color:#ffd166">{state_counts["unaddressed"]}</b><span>Unaddressed</span></div>'
        f'<div class="metric" data-tooltip="{html.escape(metric_tips["na"])}"><b style="color:#718096">{state_counts["na"]}</b><span>In-scope N/A</span></div>'
    )

    filter_bar = f"""
    <div class="card-head fw-filter-bar">
      <input type="search" id="fw-{framework}-search" placeholder="Search row ID or description..." class="fw-search-input">
      <select id="fw-{framework}-chapter-filter" class="fw-select">
        <option value="">All chapters</option>
      </select>
      <select id="fw-{framework}-status-filter" class="fw-select">
        <option value="">All statuses</option>
        <option value="satisfied">Satisfied</option>
        <option value="partial">Partial</option>
        <option value="failed">Failed</option>
        <option value="unaddressed">Unaddressed</option>
        <option value="na">Not applicable</option>
      </select>
      <label class="fw-toggle"><input type="checkbox" id="fw-{framework}-show-filtered"> Show out-of-scope ({filtered_count})</label>
    </div>
    """

    manual_checks_html = ""
    if framework == "ASVS":
        manual_checks_html = _render_ruleset_manual_checks(report_dir, framework, display_name, manual_items)

    # Group by chapter/family
    from collections import defaultdict
    by_group: dict[str, list] = defaultdict(list)
    for row, state, culprits, claiming, in_scope, _resolved in row_states:
        group = row.get("chapter") or row.get("group") or row.get("family") or "?"
        by_group[group].append((row, state, culprits, claiming, in_scope, _resolved))

    rows_html: list[str] = []
    for group in sorted(by_group.keys(), key=lambda g: int(g[1:]) if g[1:].isdigit() else 99):
        group_rows = by_group[group]
        group_counts = {"satisfied": 0, "partial": 0, "failed": 0, "unaddressed": 0, "na": 0}
        for _, state, _, _, in_scope, _resolved in group_rows:
            if in_scope and state in group_counts:
                group_counts[state] += 1
        group_total = sum(group_counts.values())
        group_pct = (group_counts["satisfied"] / group_total * 100) if group_total else 0
        group_partial_pct = (group_counts["partial"] / group_total * 100) if group_total else 0
        group_failed_pct = (group_counts["failed"] / group_total * 100) if group_total else 0
        group_gap_pct = (group_counts["unaddressed"] / group_total * 100) if group_total else 0
        group_na_pct = (group_counts["na"] / group_total * 100) if group_total else 0
        group_label = ASVS_CHAPTER_NAMES.get(group, group) if framework == "ASVS" else group
        rows_html.append(
            f'<tr class="category-row fw-group-header fw-group-collapsed" data-group="{html.escape(group)}" '
            f'tabindex="0" role="button" aria-expanded="false">'
            f'<td colspan="5"><div class="fw-group-summary">'
            f'<div class="fw-group-title"><span class="fw-group-caret">&gt;</span><strong>{html.escape(group)}</strong>'
            f'<span>{html.escape(group_label)}</span></div>'
            f'<div class="fw-group-coverage" aria-label="{html.escape(group)} coverage bar">'
            f'<span class="heat-seg heat-pass" style="width:{group_pct:.2f}%"></span>'
            f'<span class="heat-seg heat-partial" style="width:{group_partial_pct:.2f}%"></span>'
            f'<span class="heat-seg heat-fail" style="width:{group_failed_pct:.2f}%"></span>'
            f'<span class="heat-seg heat-gap" style="width:{group_gap_pct:.2f}%"></span>'
            f'<span class="heat-seg heat-na" style="width:{group_na_pct:.2f}%"></span>'
            f'</div>'
            f'</div></td></tr>'
        )
        for row, state, culprits, claiming, in_scope, resolved in group_rows:
            rows_html.append(_render_framework_row(framework, row, state, culprits, claiming, in_scope, resolved))

    if scope_explain:
        graph_note = '<span class="fw-scope-note">State is read from the runtime graph projection.</span>' if uses_graph_projection else ""
        scope_header = f'<div class="fw-scope-header">{scope_explain}{graph_note}</div>'
    else:
        scope_header = (
            f'<div class="fw-scope-header"><div><strong>{html.escape(display_name)}</strong> · '
            f'<code>{html.escape(scope_str)}</code> · '
            f'{applicable} applicable · {filtered_count} out-of-scope'
            f'{" · runtime graph projection" if uses_graph_projection else ""}</div></div>'
        )
    intro = (
        '<div class="page-intro"><div>'
        '<h2>Compliance Regime</h2>'
        '<ul>'
        '<li>Shows declared rules in scope for this catalog</li>'
        '<li>Expands chapters into rule-level assurance rows</li>'
        '<li>Combines automated evidence with manual checks</li>'
        f'</ul></div><code>{html.escape(display_name)}</code></div>'
    )

    rules_html = (
        f'<section class="card fw-card">'
        f'<div class="metric-grid" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr));margin-bottom:12px">{tiles}</div>'
        f'<div class="fw-chapter-note">Expand a chapter to inspect its compliance rows. The bar on each chapter shows met, partial, failed, unaddressed and N/A coverage.</div>'
        f'{filter_bar}'
        f'<table class="matrix fw-table"><thead><tr>'
        f'<th>Status</th><th>Level</th><th>Row ID</th><th>Section</th><th>FRs</th>'
        f'</tr></thead><tbody>{"".join(rows_html)}</tbody></table>'
        f'</section>'
    )
    tab_buttons = [
        f'<button type="button" class="fw-regime-tab-btn active" data-fw-tab-target="fw-{html.escape(framework)}-rules" aria-selected="true">Chapter View</button>'
    ]
    tab_panes = [
        f'<div class="fw-regime-pane active" id="fw-{html.escape(framework)}-rules">{rules_html}</div>'
    ]
    if manual_checks_html:
        tab_buttons.append(
            f'<button type="button" class="fw-regime-tab-btn" data-fw-tab-target="fw-{html.escape(framework)}-manual" aria-selected="false">Manual Steps</button>'
        )
        tab_panes.append(
            f'<div class="fw-regime-pane" id="fw-{html.escape(framework)}-manual">{manual_checks_html}</div>'
        )
    body = (
        f'{intro}'
        f'{scope_header}'
        f'<div class="fw-regime-tabs" data-regime="{html.escape(framework)}">'
        f'<div class="fw-regime-tabbar" role="tablist" aria-label="{html.escape(display_name)} views">{"".join(tab_buttons)}</div>'
        f'{"".join(tab_panes)}'
        f'</div>'
    )
    return body


def _render_ruleset_manual_checks(report_dir: Path, framework: str, display_name: str, manual_items: list[dict] | None = None) -> str:
    manual_items = manual_items if manual_items is not None else manual_evidence_items(report_dir)
    manual_total = len(manual_items)
    manual_done = sum(1 for item in manual_items if item.get("status") not in ("", "PENDING"))
    manual_scope = html.escape(framework.lower())
    if not manual_items:
        return (
            '<section class="card fw-manual-card"><div class="card-head">'
            f'<h2>{html.escape(display_name)} Manual Checks</h2><span class="meta">regime-specific human evidence</span></div>'
            f'<div class="empty-state">No {html.escape(display_name)} manual evidence checklist was generated.</div></section>'
        )
    out = [
        '<section class="card fw-manual-card"><div class="card-head">'
        f'<h2>{html.escape(display_name)} Manual Checks</h2><span class="meta">regime-specific human evidence</span></div>',
        f'<div class="manual-checklist" data-manual-scope="{manual_scope}" data-manual-total="{manual_total}" data-manual-initial="{manual_done}">',
        '<div class="manual-tools">',
        f'<strong>Manual completion <span class="manual-progress">{manual_done}/{manual_total}</span></strong>',
        '<div class="manual-actions"><button type="button" class="mini-btn" data-manual-select="all">Select all</button>',
        '<button type="button" class="mini-btn" data-manual-select="none">Clear</button></div>',
        '</div>',
        '<table class="manual-table"><thead><tr><th class="check-col">Done</th><th class="item-col">Manual step</th><th>What to verify</th><th>Evidence to collect</th></tr></thead><tbody>',
    ]
    for item in manual_items:
        checked = item.get("status") not in ("", "PENDING")
        item_id = f'asvs-manual-{html.escape(str(item.get("id", "")))}'
        desc = item.get("description") or ""
        why = item.get("why_required") or item.get("why") or ""
        evidence_required = item.get("evidence_expected") or item.get("evidence") or ""
        out.append(
            '<tr>'
            f'<td class="check-col"><input type="checkbox" data-manual-check="{html.escape(str(item.get("id", "")))}" id="{item_id}"{" checked" if checked else ""}></td>'
            f'<td class="item-col"><label for="{item_id}">{html.escape(str(item.get("id", "")))}. {html.escape(str(item.get("title", "")))}</label></td>'
            f'<td><div class="manual-desc">{html.escape(desc)}</div><div class="manual-evidence">{html.escape(why)}</div></td>'
            f'<td><div class="manual-desc">{html.escape(evidence_required)}</div></td>'
            '</tr>'
        )
    out.append('</tbody></table></div></section>')
    return "".join(out)


def _framework_state_from_resolved_status(status: str) -> str:
    return {
        "passed": "satisfied",
        "partial": "partial",
        "manual_review": "partial",
        "waived": "partial",
        "compensating_control": "partial",
        "failed": "failed",
        "missing": "unaddressed",
        "out_of_scope": "filtered",
        "not_applicable": "na",
        "na": "na",
    }.get(status, status or "unaddressed")


def _resolved_rows_for_framework(assurance_status: dict[str, Any] | None, framework: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not assurance_status:
        return rows
    for item in assurance_status.get("compliance_rows") or []:
        if item.get("ruleset") != framework:
            continue
        row_id = item.get("row_id") or str(item.get("id", "")).split(":", 1)[-1]
        if row_id:
            rows[row_id] = item
    return rows


def _render_resolved_assurance_detail(resolved: dict | None) -> str:
    if not resolved:
        return ""
    status = html.escape(str(resolved.get("status", "unknown")))
    reason_items = "".join(
        f"<li>{html.escape(str(reason))}</li>"
        for reason in (resolved.get("reasons") or [])[:8]
    )
    tbt_items = "".join(
        f'<code class="fw-fr-link">{html.escape(str(tbt))}</code>'
        for tbt in (resolved.get("tbt_refs") or [])
    ) or "—"
    sufficiency = resolved.get("sufficiency") or {}
    sufficiency_bits = []
    if sufficiency:
        if sufficiency.get("minimum_strength"):
            sufficiency_bits.append(f'minimum strength <code>{html.escape(str(sufficiency.get("minimum_strength")))}</code>')
        if sufficiency.get("requires_manual_review"):
            sufficiency_bits.append("manual review required")
        if sufficiency.get("scanner_only_sufficient") is not None:
            sufficiency_bits.append(f'scanner-only sufficient <code>{str(bool(sufficiency.get("scanner_only_sufficient"))).lower()}</code>')
    sufficiency_html = "; ".join(sufficiency_bits) or "No extra sufficiency constraints declared."
    scanner_evidence_html = _render_resolved_scanner_evidence(
        resolved.get("scanner_evidence") or [],
        resolved.get("scanner_blockers") or [],
    )
    reasons_html = '<ul class="fw-culprit-list" role="list">' + reason_items + "</ul>" if reason_items else ""
    return (
        '<div class="fw-row-detail fw-resolved-detail">'
        f'<strong>Resolved assurance:</strong> <span class="graph-node-status graph-status-{status}">{status}</span>'
        f'<div class="fw-row-detail-meta"><span>TBTs:</span> {tbt_items}</div>'
        f'<div class="fw-row-detail-meta"><span>Sufficiency:</span> {sufficiency_html}</div>'
        f'{reasons_html}'
        f'{scanner_evidence_html}'
        '</div>'
    )


def _render_resolved_scanner_evidence(scanner_evidence: list[dict], blockers: list[dict]) -> str:
    evidence = list(scanner_evidence or [])
    if not evidence:
        evidence = list(blockers or [])
    if not evidence:
        return ""
    blocker_keys = {
        str(item.get("id") or item.get("mapping_id") or item.get("source_locator") or item)
        for item in blockers or []
    }
    items = []
    for signal in evidence[:8]:
        normalized = signal.get("normalized_finding") or {}
        tool = signal.get("tool") or normalized.get("scanner") or "scanner"
        mapping = signal.get("mapping_id") or ""
        rule = normalized.get("rule_id") or signal.get("rule_id") or ""
        locator = signal.get("source_locator") or normalized.get("location") or signal.get("source") or ""
        message = normalized.get("message") or signal.get("message") or ""
        status = signal.get("status") or "unknown"
        effect = signal.get("assurance_effect") or ""
        strength = signal.get("strength") or signal.get("evidence_strength") or ""
        key = str(signal.get("id") or signal.get("mapping_id") or signal.get("source_locator") or signal)
        blocks = bool(signal.get("blocks_compliance")) or key in blocker_keys
        badge = "blocks" if blocks else "mapped"
        rule_html = f":<code>{html.escape(str(rule))}</code>" if rule else ""
        message_html = f"<span>{html.escape(short_text(str(message), 120))}</span>" if message else ""
        mapping_html = f'<div class="manual-evidence">Mapping: {html.escape(str(mapping))}</div>' if mapping else ""
        effect_html = (
            f'<div class="manual-evidence">Effect: {html.escape(str(effect))}; '
            f'strength: {html.escape(str(strength))}</div>'
            if effect or strength else ""
        )
        locator_html = f'<div class="manual-evidence">{html.escape(str(locator))}</div>' if locator else ""
        items.append(
            '<li class="fw-culprit-item">'
            f'<span class="graph-node-status graph-status-{html.escape(str(status))}">{html.escape(str(status))}</span> '
            f'<code>{html.escape(str(tool))}</code>'
            f'{rule_html} '
            f'<em>{html.escape(badge)}</em> '
            f'{message_html}'
            f'{mapping_html}'
            f'{effect_html}'
            f'{locator_html}'
            '</li>'
        )
    if len(evidence) > 8:
        items.append(f'<li class="fw-culprit-item"><em>and {len(evidence) - 8} more mapped scanner signal(s)</em></li>')
    return (
        '<div class="fw-row-detail-meta fw-scanner-blockers">'
        '<span>Mapped scanner evidence:</span>'
        '<div class="manual-evidence">Direct scanner mappings are independent compliance evidence. Failed blocking signals block this row; supporting signals add context but do not replace required TBT evidence.</div>'
        f'<ul class="fw-culprit-list" role="list">{"".join(items)}</ul>'
        '</div>'
    )


def _render_framework_row(framework: str, row: dict, state: str,
                          culprits: list[dict], claiming: list[str], in_scope: bool,
                          resolved: dict | None = None) -> str:
    """Render one compliance row in the framework table."""
    rid = html.escape(row.get("id", ""))
    section = html.escape(row.get("section") or row.get("family") or "")
    level_raw = row.get("level")
    level = f'L{html.escape(str(level_raw).upper().lstrip("L"))}' if level_raw is not None else "—"
    group_key = html.escape(row.get("chapter") or row.get("group") or row.get("family") or row.get("section") or "?")
    html.escape(row.get("title") or "")
    desc_raw = row.get("description", "")
    # Strip NIST parameter placeholders for display
    import re
    desc_clean = re.sub(r"\{\{\s*insert:\s*param,\s*[^}]+\}\}", "[param]", desc_raw)

    state_styles = {
        "satisfied": ("background:#35d07f;color:#081014", "pass"),
        "partial": ("background:#8fcbe8;color:#081014", "part"),
        "failed": ("background:#ff4d6d;color:#fff", "fail"),
        "unaddressed": ("background:#ffd166;color:#081014", "gap"),
        "na": ("background:repeating-linear-gradient(45deg,#718096,#718096 4px,#3a4750 4px,#3a4750 8px);color:#fff", "N/A"),
        "filtered": ("background:#2a343b;color:#718096", "OOS"),
    }
    css, label = state_styles.get(state, state_styles["filtered"])
    badge = (
        f'<span class="fw-state-badge" style="{css}" '
        f'aria-label="{html.escape(state)}">{html.escape(label)}</span>'
    )

    claiming_html = "".join(f'<code class="fw-fr-link">{html.escape(f)}</code>' for f in claiming) or "—"

    # Culprit detail (hidden by default)
    culprit_html = ""
    if culprits:
        items = []
        for c in culprits:
            sev = c.get("severity", "")
            sev_b = sev_badge(sev) if sev else ""
            items.append(
                f'<li class="fw-culprit-item">{sev_b} '
                f'<code>{html.escape(c.get("scanner", ""))}</code>:'
                f'<code>{html.escape(c.get("rule_id", ""))}</code> '
                f'<code>{html.escape(short_text(c.get("location", "-"), 60))}</code> '
                f'<span>{html.escape(short_text(c.get("message", ""), 100))}</span></li>'
            )
        culprit_html = f'<ul class="fw-culprit-list" role="list">{"".join(items)}</ul>'

    detail_html = ""
    if desc_raw or claiming or culprits or resolved:
        detail_parts = []
        resolved_html = _render_resolved_assurance_detail(resolved)
        if resolved_html:
            detail_parts.append(resolved_html)
        if claiming:
            detail_parts.append(f'<div class="fw-row-detail"><strong>Claimed by:</strong> {claiming_html}</div>')
        detail_parts.append(
            f'<div class="fw-row-detail fw-trace-detail"><strong>Trace chain:</strong>'
            f'<div class="mini-trace-caption">Row proof view: this shows only the selected row, claiming FRs, required tests and evidence.</div>'
            f'<div class="mini-trace" data-trace-node="{html.escape(framework)}:{rid}">'
            f'<div class="mini-trace-empty">Open the trace graph to load this row chain.</div>'
            f'</div><div class="mini-trace-detail graph-detail-panel" aria-live="polite">'
            f'<div class="mini-trace-empty">Select a node to inspect the suggested test, evidence state and neighbouring links.</div>'
            f'</div></div>'
        )
        if culprit_html:
            evidence_label = "Evidence gaps" if state == "partial" else "Failing evidence"
            detail_parts.append(f'<div class="fw-row-detail"><strong>{evidence_label}:</strong>{culprit_html}</div>')
        detail_html = f'<div class="fw-detail">{"".join(detail_parts)}</div>'

    hidden_class = "" if in_scope else " fw-row-filtered"
    search_text = html.escape(" ".join([row.get("id", ""), row.get("section") or row.get("family") or "", desc_clean or row.get("title") or ""]))
    return (
        f'<tr class="fw-row{hidden_class}" data-state="{state}" data-row-id="{rid}" '
        f'data-group="{group_key}" data-search-text="{search_text}" tabindex="0" role="button" aria-expanded="false">'
        f'<td>{badge}</td>'
        f'<td><span class="fw-level-badge">{level}</span></td>'
        f'<td><code>{rid}</code></td>'
        f'<td>{section}</td>'
        f'<td>{claiming_html}</td>'
        f'</tr>'
        + (f'<tr class="fw-detail-row" data-row-id="{rid}" hidden><td colspan="5">{detail_html}</td></tr>' if detail_html else "")
    )


# ===========================================================================
