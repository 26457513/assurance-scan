#!/usr/bin/env python3
"""Framework compliance tab renderer with traffic lights."""
from __future__ import annotations

import html
import re
import json
from pathlib import Path
from typing import Any

from generate_dashboard import (
    ICONS,
    C,
    SEVERITY_COLORS,
    load_json,
    short_text,
    sev_badge,
    output_candidates,
    location_label,
)

# Framework tabs (Phase 1.6 — ASVS / NIST / etc. with traffic lights)
# ===========================================================================

# Map framework name (as used in fr-catalog scope) -> bundled snapshot path + display name
FRAMEWORK_SNAPSHOTS = {
    "ASVS": ("frameworks/asvs/requirements.json", "ASVS"),
    "NIST-800-53": ("frameworks/nist_800_53/requirements.json", "NIST 800-53"),
}


def _framework_requirements(framework: str) -> list[dict]:
    """Load framework requirement rows from bundled snapshot."""
    spec = FRAMEWORK_SNAPSHOTS.get(framework)
    if not spec:
        return []
    rel_path, _ = spec
    path = Path(__file__).resolve().parent.parent.parent / "data" / rel_path
    if not path.exists():
        return []
    data = load_json(path) or {}
    return data.get("requirements") or []


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


def _compute_fr_evidence_status(req: dict, report_dir: Path) -> tuple[str, list[dict]]:
    """Return (status, failing_evidence) for one FR.

    status: 'passed' | 'failed' | 'missing'
    failing_evidence: list of dicts with scanner/rule/location/message
    """
    failing: list[dict] = []
    has_any_evidence = False
    for vb in req.get("verified_by") or []:
        vtype = vb.get("type")
        ref = vb.get("ref", "")
        if vtype == "scanner":
            # Parse 'scanner_name:pattern'
            if ":" not in ref:
                continue
            scanner, pattern = ref.split(":", 1)
            findings = _scanner_findings_for_rule(scanner, pattern, report_dir)
            has_any_evidence = True
            if findings:
                for f in findings:
                    f["scanner"] = scanner
                    failing.append(f)
        # unit/integration/e2e: no JUnit XML support yet in Phase 1.6 — treat as missing
    if failing:
        return "failed", failing
    if has_any_evidence:
        return "passed", []
    return "missing", []


def _compute_compliance_row_state(
    row_id: str,
    framework: str,
    fr_catalog: Any,
    fr_evidence: dict[str, tuple[str, list[dict]]],
) -> tuple[str, list[dict], list[str]]:
    """Return (state, culprit_findings, claiming_fr_ids).

    state: 'satisfied' | 'failed' | 'unaddressed' | 'na' | 'filtered'
    """
    # Check na_rows first (top-level project declaration)
    for na in fr_catalog.na_rows:
        if na.get("framework") == framework and na.get("row") == row_id:
            return "na", [], []

    # Find FRs claiming this row
    claiming_frs: list[str] = []
    for req in fr_catalog.requirements:
        for sat in req.get("satisfies") or []:
            if sat.get("framework") == framework and sat.get("row") == row_id:
                if sat.get("status") == "na":
                    return "na", [], [req["id"]]
                claiming_frs.append(req["id"])
                break

    if not claiming_frs:
        return "unaddressed", [], []

    # Aggregate evidence status across claiming FRs
    all_culprits: list[dict] = []
    any_failed = False
    any_passed = False
    for fr_id in claiming_frs:
        status, culprits = fr_evidence.get(fr_id, ("missing", []))
        if status == "failed":
            any_failed = True
            for c in culprits:
                c["fr_id"] = fr_id
                all_culprits.append(c)
        elif status == "passed":
            any_passed = True

    if any_failed:
        return "failed", all_culprits, claiming_frs
    if any_passed:
        return "satisfied", [], claiming_frs
    return "unaddressed", [], claiming_frs  # all claiming FRs have missing evidence


def render_framework_tab(framework: str, fr_catalog: Any, report_dir: Path) -> str:
    """Render one framework tab (ASVS, NIST 800-53, etc.)."""
    rows = _framework_requirements(framework)
    if not rows:
        return (
            f'<section class="card"><div class="empty-state">'
            f'Framework snapshot for {html.escape(framework)} not bundled. '
            f'Run scripts/build-mapping-sources.py and rebuild.</div></section>'
        )

    # Apply scope filter
    scope_entry = fr_catalog.scope.get(framework) or {}
    levels = scope_entry.get("levels") or scope_entry.get("baselines") or scope_entry.get("saq") or scope_entry.get("tier")
    if levels:
        # Normalise scope levels to a comparable set.
        # ASVS levels come as integers (1, 2, 3) in the snapshot but strings ("L1", "L2") in scope.
        # NIST baselines come as strings in both places.
        levels_norm = set()
        for l in levels:
            s = str(l).upper().lstrip("L")
            levels_norm.add(s)          # "1", "2", "3" (numeric)
            levels_norm.add(f"L{s}")    # "L1", "L2", "L3" (prefixed)
            levels_norm.add(str(l).upper())  # original uppercase form
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
    fr_evidence: dict[str, tuple[str, list[dict]]] = {}
    for req in fr_catalog.requirements:
        fr_evidence[req["id"]] = _compute_fr_evidence_status(req, report_dir)

    # Compute row states
    state_counts = {"satisfied": 0, "failed": 0, "unaddressed": 0, "na": 0, "filtered": filtered_count}
    row_states: list[tuple[dict, str, list[dict], list[str], bool]] = []
    for row, in_scope in in_scope_rows:
        if not in_scope:
            row_states.append((row, "filtered", [], [], False))
            continue
        state, culprits, claiming = _compute_compliance_row_state(
            row["id"], framework, fr_catalog, fr_evidence
        )
        state_counts[state] = state_counts.get(state, 0) + 1
        row_states.append((row, state, culprits, claiming, True))

    applicable = state_counts["satisfied"] + state_counts["failed"] + state_counts["unaddressed"] + state_counts["na"]
    coverage_pct = (state_counts["satisfied"] / applicable * 100) if applicable else 0

    display_name = FRAMEWORK_SNAPSHOTS.get(framework, (None, framework))[1]
    scope_str = ", ".join(f"{k}: {','.join(v)}" for k, v in scope_entry.items()) if scope_entry else "all levels"

    tiles = (
        f'<div class="metric"><b style="color:#35d07f">{state_counts["satisfied"]}</b><span>Satisfied</span></div>'
        f'<div class="metric"><b style="color:#ff4d6d">{state_counts["failed"]}</b><span>Failed</span></div>'
        f'<div class="metric"><b style="color:#ffd166">{state_counts["unaddressed"]}</b><span>Unaddressed</span></div>'
        f'<div class="metric"><b style="color:#718096">{state_counts["na"]}</b><span>N/A</span></div>'
        f'<div class="metric"><b style="color:#56c7b7">{coverage_pct:.0f}%</b>'
        f'<span>{state_counts["satisfied"]} of {applicable} applicable covered</span></div>'
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
        <option value="failed">Failed</option>
        <option value="unaddressed">Unaddressed</option>
        <option value="na">Not applicable</option>
      </select>
      <label class="fw-toggle"><input type="checkbox" id="fw-{framework}-show-filtered"> Show out-of-scope ({filtered_count})</label>
    </div>
    """

    # Group by chapter/family
    from collections import defaultdict
    by_group: dict[str, list] = defaultdict(list)
    for row, state, culprits, claiming, in_scope in row_states:
        group = row.get("chapter") or row.get("family") or "?"
        by_group[group].append((row, state, culprits, claiming, in_scope))

    rows_html: list[str] = []
    for group in sorted(by_group.keys(), key=lambda g: int(g[1:]) if g[1:].isdigit() else 99):
        group_rows = by_group[group]
        visible_count = sum(1 for r in group_rows if r[4] and r[1] != "filtered")
        rows_html.append(
            f'<tr class="category-row fw-group-header" data-group="{html.escape(group)}">'
            f'<td colspan="5">{html.escape(group)} '
            f'<span class="category-meta">· {visible_count} in-scope rows</span></td></tr>'
        )
        for row, state, culprits, claiming, in_scope in group_rows:
            rows_html.append(_render_framework_row(framework, row, state, culprits, claiming, in_scope))

    scope_header = (
        f'<div class="fw-scope-header">{html.escape(display_name)} · '
        f'<code>{html.escape(scope_str)}</code> · '
        f'{applicable} applicable, {filtered_count} out-of-scope</div>'
    )

    body = (
        f'{scope_header}'
        f'<section class="card fw-card">'
        f'<div class="metric-grid" style="grid-template-columns:repeat(5,minmax(100px,1fr));margin-bottom:12px">{tiles}</div>'
        f'{filter_bar}'
        f'<table class="matrix fw-table"><thead><tr>'
        f'<th>Status</th><th>Row ID</th><th>Section</th><th>Requirement</th><th>FRs</th>'
        f'</tr></thead><tbody>{"".join(rows_html)}</tbody></table>'
        f'</section>'
    )
    return body


def _render_framework_row(framework: str, row: dict, state: str,
                          culprits: list[dict], claiming: list[str], in_scope: bool) -> str:
    """Render one compliance row in the framework table."""
    rid = html.escape(row.get("id", ""))
    section = html.escape(row.get("section") or row.get("family") or "")
    title = html.escape(row.get("title") or "")
    desc_raw = row.get("description", "")
    # Strip NIST parameter placeholders for display
    import re
    desc_clean = re.sub(r"\{\{\s*insert:\s*param,\s*[^}]+\}\}", "[param]", desc_raw)
    desc = html.escape(short_text(desc_clean, 120))

    state_styles = {
        "satisfied": ("background:#35d07f;color:#081014", "pass"),
        "failed": ("background:#ff4d6d;color:#fff", "fail"),
        "unaddressed": ("background:#ffd166;color:#081014", "unaddressed"),
        "na": ("background:repeating-linear-gradient(45deg,#718096,#718096 4px,#3a4750 4px,#3a4750 8px);color:#fff", "N/A"),
        "filtered": ("background:#2a343b;color:#718096", "out of scope"),
    }
    css, label = state_styles.get(state, state_styles["filtered"])
    badge = (
        f'<span class="fw-state-badge" style="{css}" '
        f'aria-label="{html.escape(label)}">{html.escape(label)}</span>'
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
    if desc_raw or claiming or culprits:
        detail_parts = []
        if desc_raw:
            detail_parts.append(f'<div class="fw-row-desc">{html.escape(desc_clean)}</div>')
        if claiming:
            detail_parts.append(f'<div class="fw-row-detail"><strong>Claimed by:</strong> {claiming_html}</div>')
        if culprit_html:
            detail_parts.append(f'<div class="fw-row-detail"><strong>Failing evidence:</strong>{culprit_html}</div>')
        detail_html = f'<div class="fw-detail">{"".join(detail_parts)}</div>'

    hidden_class = "" if in_scope else " fw-row-filtered"
    return (
        f'<tr class="fw-row{hidden_class}" data-state="{state}" data-row-id="{rid}" '
        f'data-group="{html.escape(section)}" tabindex="0" role="button" aria-expanded="false">'
        f'<td>{badge}</td>'
        f'<td><code>{rid}</code></td>'
        f'<td>{section}</td>'
        f'<td>{desc or title}</td>'
        f'<td>{claiming_html}</td>'
        f'</tr>'
        + (f'<tr class="fw-detail-row" data-row-id="{rid}" hidden><td colspan="5">{detail_html}</td></tr>' if detail_html else "")
    )


# ===========================================================================
