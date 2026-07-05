#!/usr/bin/env python3
"""Generate a polished, tabbed HTML dashboard for a scan bundle.

Output: <report_dir>/dashboard.html

Tabs:
  - Overview  : hero scorecard, KPI gauges/donuts, headline charts
  - Scanners  : one card per scanner with description, health, raw-output link
  - Findings  : top CVEs, top secrets, most-vulnerable packages, ignored files
  - Fix Plan  : embedded agent prompt with copy button
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from scanner_parsers import *  # noqa: F401,F403 — constants, parsers, chart helpers

_css_path = Path(__file__).resolve().parent.parent / "assets" / "dashboard.css"
CSS = _css_path.read_text() if _css_path.exists() else ""



# ===========================================================================
# Palette
# ===========================================================================



# ===========================================================================
# Scanner catalogue (descriptions for the Scanners tab)
# ===========================================================================


# ===========================================================================
# Loaders / extractors
# ===========================================================================

def render_matrix(evidence: dict, ignored: dict, *, include_skipped: bool = True) -> str:
    scanner_health = evidence.get('scanner_health', {})
    findings = evidence.get('findings_summary', {})
    rows = []
    used = set()

    def scanner_row(name: str) -> str:
        health = scanner_health.get(name, {}) or {}
        status = health.get('status', 'SKIPPED')
        info = SCANNERS.get(name, {'title': name, 'level': '-', 'category': '', 'output': ''})
        reason = health.get('reason', 'Not requested')
        fv = scanner_finding_value(name, findings)
        ignored_note = ''
        if name in ignored:
            ii = ignored[name]
            ignored_note = f' <span title="filtered by .scannerignore">-{ii["removed"]}</span>'
        return (
            '<tr>'
            f'<td class="scanner">{html.escape(info.get("title", name))}</td>'
            f'<td class="level">L{html.escape(str(info.get("level", "-")))}</td>'
            f'<td class="status-col">{status_pill(status)}</td>'
            f'<td class="findings-col">{finding_markup(fv)}{ignored_note}</td>'
            f'<td><div class="reason" title="{html.escape(reason)}">{html.escape(reason)}</div></td>'
            f'<td class="evidence-col">{evidence_markup(evidence, name)}</td>'
            '</tr>'
        )



    for label, meta, names in scan_surface_groups():
        present = []
        for name in names:
            if name not in scanner_health:
                continue
            status = (scanner_health.get(name) or {}).get('status', 'SKIPPED')
            if status == 'SKIPPED' and not include_skipped:
                continue
            present.append(name)
        if not present:
            continue
        rows.append(f'<tr class="category-row"><td colspan="6">{html.escape(label)}<span class="category-meta"> · {html.escape(meta)}</span></td></tr>')
        for name in present:
            used.add(name)
            rows.append(scanner_row(name))

    remaining = []
    for name in scanner_health:
        if name in used:
            continue
        status = (scanner_health.get(name) or {}).get('status', 'SKIPPED')
        if status == 'SKIPPED' and not include_skipped:
            continue
        remaining.append(name)
    if remaining:
        rows.append('<tr class="category-row"><td colspan="6">Other<span class="category-meta"> · additional scanner outputs</span></td></tr>')
        for name in remaining:
            rows.append(scanner_row(name))

    if not rows:
        rows.append('<tr><td colspan="6" class="empty-state">No scanner data.</td></tr>')
    return (
        '<table class="matrix"><thead><tr>'
        '<th>Scanner</th><th>Tier</th><th>Status</th><th>Findings</th><th>Signal</th><th>Evidence</th>'
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
    )


def render_severity_panel(sev: dict, assurance: dict) -> str:
    total = sum(sev.values()) or 1
    rows = []
    for label in SEVERITY_ORDER:
        n = sev.get(label, 0)
        w = 0 if not n else max(3, (n / total) * 100)
        rows.append(
            f'<div class="sev-row"><label>{label}</label><div class="track">'
            f'<div class="fill" style="--w:{w:.1f}%;--bar:{SEVERITY_COLORS[label]}"></div></div><strong>{n}</strong></div>'
        )
    auto_pct = assurance.get('automated_assurance_pct', 0)
    asvs_pct = assurance.get('asvs_traceability_pct', auto_pct)
    manual_done = assurance.get('manual_items_completed', 0)
    manual_total = assurance.get('manual_items_total', 0)
    attempted = assurance.get('attempted_scanners', 0)
    skipped = assurance.get('skipped', 0)
    total_scans = attempted + skipped
    tooltip = (
        f'ASVS traceability score\n'
        f'70% automated assurance + 30% manual evidence\n\n'
        f'Automated assurance: {auto_pct}%\n'
        f'PASS = 1, WARN = 0.5, FAIL = 0\n\n'
        f'Manual evidence: {manual_done}/{manual_total}\n'
        f'Current score: round(0.7 x {auto_pct}% + 0.3 x manual completion)'
    )
    mini = (
        f'<div class="severity-mini"><div><span class="score-label">Assurance Score</span>'
        f'<svg class="score-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M13 6l6 6-6 6"/></svg>'
        f'<b id="assurance-score" data-auto-pct="{auto_pct}" data-manual-done="{manual_done}" data-manual-total="{manual_total}" data-tooltip="{html.escape(tooltip)}">{asvs_pct}%</b></div><code>{attempted}/{total_scans} scans run</code></div>'
    )
    return f'<div class="risk-rail"><div class="severity-stack">{"".join(rows)}{mini}</div></div>'

def short_text(value, limit: int = 150) -> str:
    text = str(value or '-').replace('\n', ' ').strip()
    text = re.sub(r'\s+', ' ', text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + '…'


def location_label(path: str, line=None) -> str:
    loc = str(path or '-')
    if line:
        loc += f':{line}'
    return loc


def render_detail_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return '<div class="empty-state">No row-level findings available for this scanner.</div>'
    head = ''.join(f'<th>{html.escape(h)}</th>' for h in headers)
    body = []
    for row in rows:
        cells = []
        for cell in row:
            cells.append(f'<td>{cell}</td>')
        body.append('<tr>' + ''.join(cells) + '</tr>')
    return '<table class="finding-detail"><thead><tr>' + head + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table>'


def output_candidates(report_dir: Path, rel: str, include_suffixed: bool = False) -> list[Path]:
    base = report_dir / rel
    parent = base.parent
    name = base.name
    if name.endswith('.cyclonedx.json'):
        prefix = name[: -len('.cyclonedx.json')]
        suffix = '.cyclonedx.json'
    else:
        suffix = ''.join(base.suffixes) or base.suffix
        prefix = name[: -len(suffix)] if suffix else name
    candidates: list[Path] = []
    if base.exists() and base.stat().st_size > 0:
        candidates.append(base)
    if include_suffixed and parent.is_dir():
        for path in sorted(parent.glob(f'{prefix}-*{suffix}')):
            if path.is_file() and path.stat().st_size > 0 and path not in candidates:
                candidates.append(path)
    return candidates


def target_from_output_path(path: Path, prefix: str, suffix: str) -> str:
    name = path.name
    if name == f'{prefix}{suffix}':
        return '-'
    if name.startswith(f'{prefix}-') and name.endswith(suffix):
        return name[len(prefix) + 1 : -len(suffix)]
    return '-'


def semgrep_detail_rows(report_dir: Path) -> tuple[list[str], list[list[str]]]:
    data = load_json(report_dir / 'reports' / 'semgrep.sarif') or {}
    results = ((data.get('runs') or [{}])[0].get('results') or []) if isinstance(data, dict) else []
    rows = []
    for item in results:
        loc = (((item.get('locations') or [{}])[0].get('physicalLocation') or {}))
        artifact = (loc.get('artifactLocation') or {}).get('uri', '-')
        region = loc.get('region') or {}
        line = region.get('startLine')
        rule = item.get('ruleId', '-')
        msg = (item.get('message') or {}).get('text', '-')
        rows.append([
            f'<code title="{html.escape(rule)}">{html.escape(short_text(rule, 70))}</code>',
            f'<code title="{html.escape(location_label(artifact, line))}">{html.escape(short_text(location_label(artifact, line), 80))}</code>',
            f'<div class="finding-message" title="{html.escape(msg)}">{html.escape(short_text(msg, 170))}</div>',
        ])
    return ['Rule', 'Location', 'Message'], rows


def gitleaks_detail_rows(report_dir: Path) -> tuple[list[str], list[list[str]]]:
    data = load_json(report_dir / 'reports' / 'gitleaks.json') or []
    rows = []
    if not isinstance(data, list):
        return ['Rule', 'Location', 'Description'], rows
    for item in data:
        rule = item.get('RuleID', '-')
        path = item.get('File', '-')
        line = item.get('StartLine')
        desc = item.get('Description', '-')
        rows.append([
            f'<code>{html.escape(short_text(rule, 44))}</code>',
            f'<code title="{html.escape(location_label(path, line))}">{html.escape(short_text(location_label(path, line), 90))}</code>',
            f'<div class="finding-message" title="{html.escape(desc)}">{html.escape(short_text(desc, 160))}</div>',
        ])
    return ['Rule', 'Location', 'Description'], rows


def trivy_detail_rows(report_dir: Path, rel: str, include_suffixed: bool = False) -> tuple[list[str], list[list[str]]]:
    rows = []
    for path in output_candidates(report_dir, rel, include_suffixed):
        data = load_json(path) or {}
        image_target = target_from_output_path(path, 'trivy-image', '.json')
        for result in data.get('Results', []) or []:
            target = result.get('Target', '-')
            display_target = target if image_target == '-' else f'{image_target} / {target}'
            for vuln in result.get('Vulnerabilities') or []:
                fixed = ', '.join(vuln.get('FixedVersion') or []) if isinstance(vuln.get('FixedVersion'), list) else (vuln.get('FixedVersion') or '-')
                rows.append([
                    sev_badge(str(vuln.get('Severity', 'UNKNOWN')).upper()),
                    f'<code>{html.escape(vuln.get("VulnerabilityID", "-"))}</code>',
                    f'<code title="{html.escape(display_target)}">{html.escape(short_text(display_target, 74))}</code>',
                    f'<div class="finding-message">{html.escape(short_text(vuln.get("PkgName", "-"), 80))} {html.escape(short_text(vuln.get("InstalledVersion", ""), 40))}</div>',
                    html.escape(short_text(fixed, 80)),
                ])
            for secret in result.get('Secrets') or []:
                rows.append([
                    sev_badge(str(secret.get('Severity', 'UNKNOWN')).upper()),
                    f'<code>{html.escape(secret.get("RuleID", "-"))}</code>',
                    f'<code title="{html.escape(location_label(display_target, secret.get("StartLine")))}">{html.escape(short_text(location_label(display_target, secret.get("StartLine")), 74))}</code>',
                    f'<div class="finding-message">{html.escape(short_text(secret.get("Title", secret.get("Category", "Secret")), 100))}</div>',
                    '-',
                ])
            for misconf in result.get('Misconfigurations') or []:
                if misconf.get('Status') and misconf.get('Status') != 'FAIL':
                    continue
                rows.append([
                    sev_badge(str(misconf.get('Severity', 'UNKNOWN')).upper()),
                    f'<code>{html.escape(misconf.get("ID", "-"))}</code>',
                    f'<code title="{html.escape(display_target)}">{html.escape(short_text(display_target, 74))}</code>',
                    f'<div class="finding-message" title="{html.escape(misconf.get("Message", ""))}">{html.escape(short_text(misconf.get("Title", misconf.get("Message", "-")), 110))}</div>',
                    html.escape(short_text(misconf.get('Resolution', '-'), 80)),
                ])
    return ['Severity', 'ID', 'Target', 'Finding', 'Fix'], rows


def grype_detail_rows(report_dir: Path, rel: str = 'reports/grype.json', include_suffixed: bool = False) -> tuple[list[str], list[list[str]]]:
    rows = []
    rank = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'UNKNOWN': 4}
    def key(match):
        sev = str(((match.get('vulnerability') or {}).get('severity') or 'UNKNOWN')).upper()
        return (rank.get(sev, 9), (match.get('vulnerability') or {}).get('id', ''))
    for path in output_candidates(report_dir, rel, include_suffixed):
        data = load_json(path) or {}
        image_target = target_from_output_path(path, 'grype-image', '.json')
        for match in sorted(data.get('matches', []) or [], key=key):
            vuln = match.get('vulnerability') or {}
            artifact = match.get('artifact') or {}
            fix = ', '.join((vuln.get('fix') or {}).get('versions') or []) or '-'
            package = artifact.get('name', '-')
            if image_target != '-':
                package = f'{image_target} / {package}'
            rows.append([
                sev_badge(str(vuln.get('severity', 'UNKNOWN')).upper()),
                f'<code>{html.escape(vuln.get("id", "-"))}</code>',
                f'<code title="{html.escape(package)}">{html.escape(short_text(package, 88))}</code>',
                html.escape(short_text(artifact.get('version', '-'), 48)),
                html.escape(short_text(fix, 90)),
            ])
    return ['Severity', 'ID', 'Package', 'Installed', 'Fixed in'], rows


def syft_detail_rows(report_dir: Path, rel: str = 'sbom/sbom.cyclonedx.json', include_suffixed: bool = False) -> tuple[list[str], list[list[str]]]:
    rows = []
    for path in output_candidates(report_dir, rel, include_suffixed):
        data = load_json(path) or {}
        image_target = target_from_output_path(path, 'image-sbom', '.cyclonedx.json')
        for comp in data.get('components', []) or []:
            props = {p.get('name'): p.get('value') for p in comp.get('properties', []) or [] if isinstance(p, dict)}
            ptype = props.get('syft:package:type') or comp.get('type', '-')
            component = comp.get('name', '-')
            if image_target != '-':
                component = f'{image_target} / {component}'
            rows.append([
                f'<code>{html.escape(short_text(ptype, 38))}</code>',
                f'<code title="{html.escape(component)}">{html.escape(short_text(component, 100))}</code>',
                html.escape(short_text(comp.get('version', '-'), 48)),
                f'<code title="{html.escape(comp.get("purl", comp.get("bom-ref", "-")))}">{html.escape(short_text(comp.get("purl", comp.get("bom-ref", "-")), 110))}</code>',
            ])
    return ['Type', 'Component', 'Version', 'Locator'], rows


def manual_evidence_items(report_dir: Path) -> list[dict]:
    manual_path = report_dir / 'manual-evidence-required.md'
    if not manual_path.exists():
        return []
    items = []
    current = None
    heading_re = re.compile(r'^##\s+(\d+)\.\s+(.+?)\s*$')
    field_re = re.compile(r'^-\s+\*\*(Description|Why required|Evidence expected|Status):\*\*\s*(.*)$')
    for line in manual_path.read_text(errors='replace').splitlines():
        heading = heading_re.match(line)
        if heading:
            if current:
                items.append(current)
            current = {
                'id': heading.group(1),
                'title': heading.group(2),
                'description': '',
                'why': '',
                'evidence': '',
                'status': 'PENDING',
            }
            continue
        if not current:
            continue
        field = field_re.match(line)
        if field:
            key = field.group(1).lower().replace(' ', '_')
            current[key] = field.group(2).strip()
    if current:
        items.append(current)
    return items


def severity_issues(report_dir: Path, wanted: set[str]) -> list[dict]:
    issues: list[dict] = []
    rank = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'UNKNOWN': 4}

    for path in output_candidates(report_dir, 'reports/grype.json', include_suffixed=True):
        image_target = target_from_output_path(path, 'grype-image', '.json')
        source = 'Grype Image' if image_target != '-' else 'Grype'
        data = load_json(path) or {}
        for match in data.get('matches', []) or []:
            vuln = match.get('vulnerability') or {}
            artifact = match.get('artifact') or {}
            severity = str(vuln.get('severity') or 'UNKNOWN').upper()
            if severity not in wanted:
                continue
            fix = ', '.join((vuln.get('fix') or {}).get('versions') or []) or '-'
            pkg = artifact.get('name', '-')
            version = artifact.get('version', '-')
            if image_target != '-':
                pkg = f'{image_target} / {pkg}'
            issues.append({
                'severity': severity,
                'source': source,
                'id': vuln.get('id', '-'),
                'target': f'{pkg} {version}'.strip(),
                'detail': fix,
            })

    trivy_sources = [
        ('reports/trivy-fs.json', 'Trivy FS', False),
        ('reports/trivy-config.json', 'Trivy Config', False),
        ('reports/trivy-image.json', 'Trivy Image', True),
    ]
    for rel, base_source, include_suffixed in trivy_sources:
        candidates = output_candidates(report_dir, rel, include_suffixed=include_suffixed)
        for path in candidates:
            image_target = target_from_output_path(path, 'trivy-image', '.json')
            source = 'Trivy Image' if image_target != '-' else base_source
            data = load_json(path) or {}
            for result in data.get('Results', []) or []:
                target = result.get('Target', '-')
                if image_target != '-':
                    target = f'{image_target} / {target}' if target != '-' else image_target
                for vuln in result.get('Vulnerabilities') or []:
                    severity = str(vuln.get('Severity') or 'UNKNOWN').upper()
                    if severity not in wanted:
                        continue
                    fixed = vuln.get('FixedVersion') or '-'
                    issues.append({
                        'severity': severity,
                        'source': source,
                        'id': vuln.get('VulnerabilityID', '-'),
                        'target': f'{vuln.get("PkgName", target)} {vuln.get("InstalledVersion", "")}'.strip(),
                        'detail': fixed if isinstance(fixed, str) else ', '.join(fixed),
                    })
                for secret in result.get('Secrets') or []:
                    severity = str(secret.get('Severity') or 'UNKNOWN').upper()
                    if severity not in wanted:
                        continue
                    issues.append({
                        'severity': severity,
                        'source': source,
                        'id': secret.get('RuleID', '-'),
                        'target': location_label(target, secret.get('StartLine')),
                        'detail': secret.get('Title') or secret.get('Category') or 'Secret',
                    })
                for misconf in result.get('Misconfigurations') or []:
                    if misconf.get('Status') and misconf.get('Status') != 'FAIL':
                        continue
                    severity = str(misconf.get('Severity') or 'UNKNOWN').upper()
                    if severity not in wanted:
                        continue
                    issues.append({
                        'severity': severity,
                        'source': source,
                        'id': misconf.get('ID', '-'),
                        'target': target,
                        'detail': misconf.get('Resolution') or misconf.get('Title') or misconf.get('Message') or '-',
                    })

    issues.sort(key=lambda x: (rank.get(x['severity'], 9), x['source'], x['id'], x['target']))
    return issues


def critical_high_issues(report_dir: Path) -> list[dict]:
    return severity_issues(report_dir, {'CRITICAL', 'HIGH'})


def medium_low_issues(report_dir: Path) -> list[dict]:
    return severity_issues(report_dir, {'MEDIUM', 'LOW'})


def scanner_detail_table(name: str, report_dir: Path) -> str:
    normalized = name.replace('_', '-')
    if normalized == 'semgrep':
        headers, rows = semgrep_detail_rows(report_dir)
    elif normalized == 'gitleaks':
        headers, rows = gitleaks_detail_rows(report_dir)
    elif normalized == 'trivy-fs':
        headers, rows = trivy_detail_rows(report_dir, 'reports/trivy-fs.json')
    elif normalized == 'trivy-config':
        headers, rows = trivy_detail_rows(report_dir, 'reports/trivy-config.json')
    elif normalized == 'trivy-image':
        headers, rows = trivy_detail_rows(report_dir, 'reports/trivy-image.json', include_suffixed=True)
    elif normalized == 'grype':
        headers, rows = grype_detail_rows(report_dir)
    elif normalized == 'grype-image':
        headers, rows = grype_detail_rows(report_dir, 'reports/grype-image.json', include_suffixed=True)
    elif normalized == 'syft':
        headers, rows = syft_detail_rows(report_dir)
    elif normalized == 'syft-image':
        headers, rows = syft_detail_rows(report_dir, 'sbom/image-sbom.cyclonedx.json', include_suffixed=True)
    else:
        return '<div class="empty-state">No row-level finding details available for this scanner.</div>'
    return render_detail_table(headers, rows)


def render_all_findings(evidence: dict, report_dir: Path) -> str:
    findings = evidence.get('findings_summary', {})
    rows = []
    ordered = [name for name in SCANNERS if scanner_finding_value(name, findings) is not None]
    ordered += [name for name in findings if name.replace('_', '-') not in ordered and name not in ordered]
    for name in ordered:
        value = scanner_finding_value(name, findings)
        total = finding_total(value)
        if total <= 0:
            continue
        title = SCANNERS.get(name, SCANNERS.get(name.replace('_', '-'), {})).get('title', name.replace('_', '-'))
        detail_id = 'finding-detail-' + re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        rows.append(
            '<tr class="finding-parent">'
            f'<td class="scanner">{html.escape(title)}</td>'
            f'<td>{finding_markup(value)}</td>'
            f'<td class="plain-count">{total:,}</td>'
            f'<td class="finding-action"><button type="button" class="finding-toggle" data-finding-toggle="{html.escape(detail_id)}" aria-controls="{html.escape(detail_id)}" aria-expanded="false">Rows</button></td>'
            '</tr>'
        )
        rows.append(
            f'<tr class="finding-detail-row" id="{html.escape(detail_id)}" hidden>'
            f'<td colspan="4">{scanner_detail_table(name, report_dir)}</td>'
            '</tr>'
        )
    if not rows:
        rows.append('<tr><td colspan="4" class="empty-state">No findings.</td></tr>')
    return (
        '<section class="card" data-overview-section="all-findings"><div class="card-head">'
        '<h2>All Findings</h2><span class="meta">scanner summaries with row-level findings</span></div>'
        '<table class="matrix"><thead><tr><th>Scanner</th><th>Breakdown</th><th>Total</th><th class="finding-action">Details</th></tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table></section>'
    )

def render_scanner_health(evidence: dict) -> str:
    scanner_health = evidence.get('scanner_health', {})
    findings = evidence.get('findings_summary', {})
    scanner_groups = [
        ('Code', 'SAST, secrets, filesystem and config analysis', ['semgrep', 'gitleaks', 'trivy-fs', 'trivy-config']),
        ('Supply Chain', 'SBOM generation and vulnerability matching', ['syft', 'grype', 'osv-scanner']),
        ('Container Image', 'built image SBOM and vulnerability checks', ['trivy-image', 'syft-image', 'grype-image']),
        ('Runtime Surface', 'web app, headers and TLS checks', ['zap-baseline', 'security-headers', 'testssl']),
        ('Uploads & Malware', 'uploaded content scanning', ['clamav']),
    ]
    used: set[str] = set()
    rows = []

    def scanner_row(name: str) -> str:
        info = SCANNERS.get(name, {'title': name, 'level': '-', 'output': '-'})
        health = scanner_health.get(name, {}) or {}
        status = health.get('status', 'SKIPPED')
        reason = health.get('reason', 'Not requested')
        fv = scanner_finding_value(name, findings)
        return (
            '<tr>'
            f'<td class="scanner">{html.escape(info.get("title", name))}</td>'
            f'<td class="level">L{html.escape(str(info.get("level", "-")))}</td>'
            f'<td class="status-col">{status_pill(status)}</td>'
            f'<td class="findings-col">{finding_markup(fv)}</td>'
            f'<td><div class="reason" title="{html.escape(reason)}">{html.escape(reason)}</div></td>'
            f'<td class="evidence-col">{evidence_markup(evidence, name)}</td>'
            '</tr>'
        )

    for label, meta, names in scanner_groups:
        present = [name for name in names if name in scanner_health]
        if not present:
            continue
        rows.append(
            f'<tr class="category-row"><td colspan="6">{html.escape(label)}'
            f'<span class="category-meta"> · {html.escape(meta)}</span></td></tr>'
        )
        for name in present:
            used.add(name)
            rows.append(scanner_row(name))

    remaining = [name for name in scanner_health if name not in used]
    if remaining:
        rows.append('<tr class="category-row"><td colspan="6">Other<span class="category-meta"> · additional scanner outputs</span></td></tr>')
        for name in remaining:
            rows.append(scanner_row(name))

    return (
        '<section class="card" data-overview-section="scanner-health"><div class="card-head">'
        '<h2>Scanners</h2><span class="meta">grouped by scan surface</span></div>'
        '<table class="matrix"><thead><tr><th>Scanner</th><th>Tier</th><th>Status</th><th>Findings</th><th>Signal</th><th>Evidence</th></tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table></section>'
    )


def render_coverage(evidence: dict, report_dir: Path) -> str:
    evidence_files = evidence.get('evidence_files', [])
    out = ['<section class="card" data-overview-section="coverage"><div class="card-head"><h2>Evidence Files</h2><span class="meta">generated files and preview</span></div>']
    if evidence_files:
        previews = []
        out.append('<div class="evidence-grid">')
        for idx, item in enumerate(evidence_files):
            rel_file = str(item.get("file", "-"))
            sha = str(item.get('sha256', ''))
            preview = read_evidence_preview(report_dir, rel_file)
            preview.update({
                'bytes': fmt_bytes(item.get('bytes', 0)),
                'sha': sha[:12],
            })
            previews.append(preview)
            out.append(
                f'<button type="button" class="evidence-item" data-preview-index="{idx}">'
                f'<div class="file"><code>{html.escape(rel_file)}</code></div>'
                f'<div class="meta"><span>{fmt_bytes(item.get("bytes", 0))}</span><span>{html.escape(sha[:12])}</span></div>'
                '</button>'
            )
        out.append('</div>')
        out.append(
            '<div class="evidence-preview">'
            '<div class="evidence-preview-bar">'
            '<div class="evidence-preview-title"><span>Preview</span><code id="evidence-preview-file">Select a file</code></div>'
            '<div class="evidence-preview-meta" id="evidence-preview-meta">-</div>'
            '</div>'
            '<div class="evidence-code" id="evidence-preview-code"><div class="evidence-preview-empty">Select an evidence file above.</div></div>'
            '<div class="evidence-truncated" id="evidence-preview-truncated" hidden>Preview truncated to keep the report responsive.</div>'
            '</div>'
        )
        out.append(evidence_preview_script(previews))
    out.append('</section>')
    return ''.join(out)


def render_manual_checklist(evidence: dict, report_dir: Path) -> str:
    assurance = evidence.get('assurance', {})
    manual_items = manual_evidence_items(report_dir)
    manual_total = assurance.get('manual_items_total', len(manual_items))
    manual_done = assurance.get('manual_items_completed', 0)
    out = [
        '<section class="card" data-overview-section="manual"><div class="card-head">'
        '<h2>Manual ASVS Checklist</h2><span class="meta">evidence that requires human review</span></div>'
    ]
    if not manual_items:
        out.append('<div class="empty-state">No manual evidence checklist was generated.</div></section>')
        return ''.join(out)

    out.append(
        f'<div class="manual-checklist" data-manual-total="{manual_total}" data-manual-initial="{manual_done}">'
        '<div class="manual-tools">'
        f'<strong>Manual completion <span id="manual-progress">{manual_done}/{manual_total}</span></strong>'
        '<div class="manual-actions"><button type="button" class="mini-btn" data-manual-select="all">Select all</button>'
        '<button type="button" class="mini-btn" data-manual-select="none">Clear</button></div>'
        '</div>'
        '<table class="manual-table"><thead><tr><th class="check-col">Done</th><th class="item-col">Manual step</th><th>What to verify</th><th>Evidence to collect</th></tr></thead><tbody>'
    )
    for item in manual_items:
        checked = item.get('status') not in ('', 'PENDING')
        desc = item.get('description') or ''
        why = item.get('why_required') or item.get('why') or ''
        evidence_required = item.get('evidence_expected') or item.get('evidence') or ''
        item_id = f'manual-{html.escape(str(item.get("id", "")))}'
        out.append(
            '<tr>'
            f'<td class="check-col"><input type="checkbox" data-manual-check="{html.escape(str(item.get("id", "")))}" id="{item_id}"{" checked" if checked else ""}></td>'
            f'<td class="item-col"><label for="{item_id}">{html.escape(str(item.get("id", "")))}. {html.escape(str(item.get("title", "")))}</label></td>'
            f'<td><div class="manual-desc">{html.escape(desc)}</div><div class="manual-evidence">{html.escape(why)}</div></td>'
            f'<td><div class="manual-desc">{html.escape(evidence_required)}</div></td>'
            '</tr>'
        )
    out.append('</tbody></table></div></section>')
    return ''.join(out)


def render_secret_detail(report_dir: Path, overview_section: bool = False) -> str:
    secret_rules, secret_files, secret_total = secret_breakdowns(report_dir / 'reports' / 'gitleaks.json')
    if not secret_total:
        return ''
    section_attr = ' data-overview-section="secrets"' if overview_section else ''
    out = [f'<div class="stack"{section_attr}>']
    out.append(
        f'<section class="card"><div class="card-head"><h2>Secrets</h2><span class="meta">{secret_total} exposed</span></div>'
        f'<div class="callout">{ICONS["alert"]}<div><strong>Rotate before code fixes.</strong> '
        f'Gitleaks found {secret_total} secrets; assume exposure until revoked.</div></div></section>'
    )
    out.append('<div class="two-col">')
    out.append(f'<section class="card"><div class="card-head"><h2>Secret Types</h2><span class="meta">{secret_total} total</span></div><div class="dense-list">')
    for rule, n in secret_rules:
        out.append(f'<div class="kv"><code>{html.escape(rule)}</code><strong>{n}</strong></div>')
    out.append('</div></section>')
    out.append('<section class="card"><div class="card-head"><h2>Secret Files</h2><span class="meta">top paths</span></div><div class="dense-list">')
    for path, n in secret_files:
        out.append(f'<div class="kv"><code title="{html.escape(path)}">{html.escape(path)}</code><strong>{n}</strong></div>')
    out.append('</div></section></div></div>')
    return ''.join(out)


def render_overview(evidence: dict, report_dir: Path, ignored: dict) -> str:
    findings = evidence.get('findings_summary', {})
    priority_issues = critical_high_issues(report_dir)
    medium_low = medium_low_issues(report_dir)
    secret_detail = render_secret_detail(report_dir, overview_section=True)
    top_pkgs = top_packages(report_dir / 'reports' / 'grype.json', limit=8)
    out = ['<div class="overview-grid">']
    out.append('<section class="card" data-overview-section="matrix"><div class="card-head"><h2>Evidence Matrix</h2><span class="meta">full scanner coverage and raw evidence paths</span></div>')
    out.append(render_matrix(evidence, ignored, include_skipped=True))
    out.append('</section>')
    out.append(render_all_findings(evidence, report_dir))
    out.append(render_scanner_health(evidence))

    if secret_detail:
        out.append(secret_detail)

    lower_cards = []
    if top_pkgs:
        hot = ['<section class="card" data-overview-section="hot-packages"><div class="card-head"><h2>Hot Packages</h2><span class="meta">by vuln count</span></div><div class="dense-list">']
        for pkg, n in top_pkgs:
            hot.append(f'<div class="kv"><code>{html.escape(pkg)}</code><strong>{n}</strong></div>')
        hot.append('</div></section>')
        lower_cards.append(''.join(hot))

    if lower_cards:
        out.append('<div class="two-col below-matrix" data-overview-group>' + ''.join(lower_cards) + '</div>')

    if priority_issues:
        out.append(f'<section class="card" data-overview-section="cves"><div class="card-head"><h2>Critical &amp; High Issues</h2><span class="meta">{len(priority_issues)} critical/high rows</span></div><table class="matrix"><thead><tr><th>Severity</th><th>Scanner</th><th>ID</th><th>Target</th><th>Fix / Detail</th></tr></thead><tbody>')
        for issue in priority_issues:
            out.append(
                f'<tr><td>{sev_badge(issue["severity"])}</td>'
                f'<td>{html.escape(issue["source"])}</td>'
                f'<td><code>{html.escape(short_text(issue["id"], 52))}</code></td>'
                f'<td><code title="{html.escape(issue["target"])}">{html.escape(short_text(issue["target"], 90))}</code></td>'
                f'<td><div class="finding-message" title="{html.escape(issue["detail"])}">{html.escape(short_text(issue["detail"], 120))}</div></td></tr>'
            )
        out.append('</tbody></table></section>')

    if medium_low:
        out.append(f'<section class="card" data-overview-section="medium-low"><div class="card-head"><h2>Medium &amp; Low Issues</h2><span class="meta">{len(medium_low)} medium/low rows</span></div><table class="matrix"><thead><tr><th>Severity</th><th>Scanner</th><th>ID</th><th>Target</th><th>Fix / Detail</th></tr></thead><tbody>')
        for issue in medium_low:
            out.append(
                f'<tr><td>{sev_badge(issue["severity"])}</td>'
                f'<td>{html.escape(issue["source"])}</td>'
                f'<td><code>{html.escape(short_text(issue["id"], 52))}</code></td>'
                f'<td><code title="{html.escape(issue["target"])}">{html.escape(short_text(issue["target"], 90))}</code></td>'
                f'<td><div class="finding-message" title="{html.escape(issue["detail"])}">{html.escape(short_text(issue["detail"], 120))}</div></td></tr>'
            )
        out.append('</tbody></table></section>')

    out.append(render_coverage(evidence, report_dir))
    out.append(render_manual_checklist(evidence, report_dir))

    out.append('</div>')
    return ''.join(out)


def render_scanners(evidence: dict, report_dir: Path, ignored: dict) -> str:
    return '<section class="card"><div class="card-head"><h2>Scanner Detail</h2><span class="meta">status, signal, and raw evidence path</span></div>' + render_matrix(evidence, ignored, include_skipped=True) + '</section>'


def render_findings(evidence: dict, report_dir: Path, ignored: dict) -> str:
    out = ['<div class="stack">']
    top_vulns = top_grype(report_dir / 'reports' / 'grype.json', limit=20)
    if top_vulns:
        out.append('<section class="card"><div class="card-head"><h2>Vulnerability Queue</h2><span class="meta">first pass triage list</span></div><table class="matrix"><thead><tr><th>Severity</th><th>CVE</th><th>Package</th><th>Installed</th><th>Fixed in</th></tr></thead><tbody>')
        for v in top_vulns:
            fix = html.escape(v['fixed_in']) if v['fixed_in'] not in ('-', '—', '') else '-'
            out.append(f'<tr><td>{sev_badge(v["severity"])}</td><td><code>{html.escape(v["id"])}</code></td><td><code>{html.escape(v["pkg"])}</code></td><td>{html.escape(v["version"])}</td><td>{fix}</td></tr>')
        out.append('</tbody></table></section>')

    secret_detail = render_secret_detail(report_dir)
    if secret_detail:
        out.append(secret_detail)

    if ignored:
        out.append('<section class="card"><div class="card-head"><h2>.scannerignore Impact</h2><span class="meta">filtered source/config findings</span></div><table class="matrix"><thead><tr><th>Scanner</th><th>Before</th><th>After</th><th>Removed</th><th>Patterns</th></tr></thead><tbody>')
        for name, info in ignored.items():
            out.append(f'<tr><td class="scanner">{html.escape(name)}</td><td>{info["before"]}</td><td>{info["after"]}</td><td><strong>{info["removed"]}</strong></td><td>{info["patterns_count"]}</td></tr>')
        out.append('</tbody></table></section>')

    out.append('</div>')
    return ''.join(out)


def render_fixplan(report_dir: Path) -> str:
    prompt_path = report_dir / "agent-investigation-prompt.md"
    prompt_md = prompt_path.read_text(errors="replace") if prompt_path.exists() else "Agentic fix prompt is not available for this run. The scan may have stopped before report generation completed."
    prompt_html = md_to_html(prompt_md)
    return f'''
<section class="section">
  <div class="prompt-shell">
    <div class="prompt-bar">
      <div>
        <h2>Agent Investigation &amp; Fix Plan</h2>
        <div class="meta">Paste this into Claude Code or another AI agent to begin triage. Six phases ordered by blast radius.</div>
      </div>
      <button class="copy-btn" onclick="copyPrompt()">{ICONS["copy"]}<span class="btn-label">Copy prompt</span></button>
    </div>
    <div class="prompt-body" id="prompt-body">{prompt_html}</div>
  </div>
</section>
'''


def kpi(label: str, value: str, accent: str, icon: str, sub: str = "") -> str:
    return (
        f'<div class="kpi" style="--accent:{accent}">'
        f'<div class="kpi-icon">{ICONS.get(icon, ICONS["shield"])}</div>'
        f'<div class="kpi-value">{html.escape(value)}</div>'
        f'<div class="kpi-label">{html.escape(label)}</div>'
        f'{f"<div class=\"kpi-sub\">{html.escape(sub)}</div>" if sub else ""}'
        f'</div>'
    )


# ===========================================================================
# Top-level
# ===========================================================================

def render(*, report_dir: Path, fr_catalog_path: str | None = None, junit_xml_path: str | None = None) -> str:
    # Lazy imports for FR-driven tabs — loaded at call time to avoid circular imports
    if fr_catalog_path:
        from fr.catalog_tab import render_fr_catalog
        from fr.framework_tab import (
            render_framework_tab, FRAMEWORK_SNAPSHOTS,
            _framework_requirements, _compute_fr_evidence_status,
            _compute_compliance_row_state,
        )

    evidence = load_json(report_dir / "evidence-manifest.json") or {}
    scanner_health = evidence.get("scanner_health", {})
    findings = evidence.get("findings_summary", {})
    assurance = evidence.get("assurance", {})
    ignored = parse_ignored_from_log(report_dir / "run.log")

    sev = aggregate_severity_strict(findings)
    total_findings = actionable_finding_total(findings)
    critical_count = sev.get('CRITICAL', 0)
    high_count = sev.get('HIGH', 0)
    medium_count = sev.get('MEDIUM', 0)
    low_count = sev.get('LOW', 0)
    rec = str(assurance.get("release_recommendation", "UNKNOWN"))
    rec_color = C["pass"] if rec == "READY" else C["fail"]
    failed = assurance.get("failed", sum(1 for info in scanner_health.values() if info.get("status") == "FAIL"))
    warned = assurance.get("warned", sum(1 for info in scanner_health.values() if info.get("status") == "WARN"))
    skipped = assurance.get("skipped", sum(1 for info in scanner_health.values() if info.get("status") == "SKIPPED"))
    secrets = findings.get("gitleaks", 0) if isinstance(findings.get("gitleaks"), int) else 0
    secret_rules, secret_files, _secret_total = secret_breakdowns(report_dir / 'reports' / 'gitleaks.json')
    secret_type_count = len(secret_rules)
    secret_file_count = len(secret_files)
    auto_pct = assurance.get("automated_assurance_pct", 0)
    asvs_pct = assurance.get("asvs_traceability_pct", 0)
    manual_done = assurance.get("manual_items_completed", 0)
    manual_total = assurance.get("manual_items_total", 0)

    overview_html = render_overview(evidence, report_dir, ignored)

    fixplan_html = render_fixplan(report_dir)
    fr_catalog_html = render_fr_catalog(fr_catalog_path) if fr_catalog_path else ""

    # Framework tabs — one per framework in the project's scope
    framework_tabs_html: list[tuple[str, str]] = []  # (tab_id, fw_name, html)
    reverse_lookup_json = "[]"
    if fr_catalog_path:
        import importlib.util
        loader_path = Path(__file__).resolve().parent / "load_fr_catalog.py"
        spec = importlib.util.spec_from_file_location("load_fr_catalog_runtime", loader_path)
        if spec and spec.loader:
            loader_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loader_mod)
            try:
                catalog = loader_mod.load_fr_catalog(Path(fr_catalog_path))
                for fw in catalog.scope:
                    if fw in FRAMEWORK_SNAPSHOTS:
                        tab_html = render_framework_tab(fw, catalog, report_dir)
                        tab_id = f"fw-{fw.lower().replace('-', '').replace('_', '')}"
                        framework_tabs_html.append((tab_id, fw, tab_html))

                # Build reverse lookup index for "Find ASVS impact" feature
                # Maps each scanner verified_by pattern to the FR IDs + compliance rows it threatens
                reverse_lookup: dict[str, dict] = {}
                for req in catalog.requirements:
                    for vb in req.get("verified_by") or []:
                        if vb.get("type") == "scanner":
                            ref = vb.get("ref", "")
                            entry = reverse_lookup.setdefault(ref, {"fr_ids": [], "compliance_rows": []})
                            if req["id"] not in entry["fr_ids"]:
                                entry["fr_ids"].append(req["id"])
                            for sat in req.get("satisfies") or []:
                                row_ref = {"framework": sat.get("framework", ""), "row": sat.get("row", "")}
                                if row_ref not in entry["compliance_rows"]:
                                    entry["compliance_rows"].append(row_ref)
                reverse_lookup_json = json.dumps(list(reverse_lookup.items()))

                # Compute coverage heatmap for overview
                if framework_tabs_html:
                    try:
                        _fr_ev = {}
                        for req in catalog.requirements:
                            _fr_ev[req["id"]] = _compute_fr_evidence_status(req, report_dir)
                        from collections import defaultdict as _dd
                        _heatmap_parts = []
                        for _, _fw, _ in framework_tabs_html:
                            _frows = _framework_requirements(_fw)
                            if not _frows:
                                continue
                            _by_grp = _dd(lambda: {"s": 0, "f": 0, "u": 0, "n": 0, "a": 0})
                            for _row in _frows:
                                _lv = _row.get("level")
                                _sc = catalog.scope.get(_fw, {})
                                _ls = _sc.get("levels") or _sc.get("baselines")
                                _ok = True
                                if _ls and _lv is not None:
                                    _ln = {str(x).upper().lstrip("L") for x in _ls}
                                    _ok = str(_lv).upper().lstrip("L") in _ln
                                if not _ok:
                                    continue
                                _st, _, _ = _compute_compliance_row_state(_row["id"], _fw, catalog, _fr_ev)
                                _g = _row.get("chapter") or _row.get("family") or "?"
                                _by_grp[_g]["a"] += 1
                                if _st in ("satisfied",): _by_grp[_g]["s"] += 1
                                elif _st in ("failed",): _by_grp[_g]["f"] += 1
                                elif _st in ("unaddressed",): _by_grp[_g]["u"] += 1
                                elif _st in ("na",): _by_grp[_g]["n"] += 1
                            _dn = FRAMEWORK_SNAPSHOTS.get(_fw, (None, _fw))[1]
                            _cells = []
                            for _g in sorted(_by_grp.keys(), key=lambda x: int(x[1:]) if x[1:].isdigit() else 99):
                                _v = _by_grp[_g]
                                if _v["a"] == 0:
                                    continue
                                _pct = (_v["s"] / _v["a"] * 100) if _v["a"] else 0
                                _col = "#35d07f" if _pct >= 75 else "#ffd166" if _pct >= 25 else "#ff4d6d"
                                _cells.append(
                                    f'<span class="heat-cell" title="{html.escape(_g)}: {_v["s"]}/{_v["a"]} ({_pct:.0f}%)">'
                                    f'<span class="heat-label">{html.escape(_g)}</span>'
                                    f'<span class="heat-pct" style="color:{_col}">{_pct:.0f}%</span>'
                                    f'<span class="heat-count">{_v["s"]}/{_v["a"]}</span></span>'
                                )
                            _heatmap_parts.append(f'<div class="heat-framework"><h3>{html.escape(_dn)}</h3><div class="heat-grid">{"".join(_cells)}</div></div>')
                        if _heatmap_parts:
                            overview_html = (
                                '<section class="card"><div class="card-head"><h2>Coverage Heatmap</h2>'
                                '<span class="meta">per-framework, per-chapter coverage</span></div>'
                                '<div class="heat-body">' + "".join(_heatmap_parts) + '</div></section>'
                            ) + overview_html
                    except Exception:
                        pass
            except loader_mod.FrCatalogError:
                pass  # error already shown in FR Catalog tab

    run_id = html.escape(str(evidence.get("run_id", "-")))
    generated = html.escape(str(evidence.get("generated_at", "-"))[:19].replace("T", " "))
    target_raw = str(evidence.get("target_dir", "-"))
    repo_name = html.escape(str(evidence.get("repository") or evidence.get("repo_name") or git_repo_name(target_raw) or "-"))
    branch = html.escape(str(evidence.get("git_branch") or "-"))
    safe_branch = html.escape(str(evidence.get("safe_scan_branch") or git_branch_name(target_raw) or "-"))
    commit = html.escape(str(evidence.get("git_commit") or "-")[:12])

    def metric(label: str, value: str, color: str = "var(--ink)", overview_filter: str | None = None) -> str:
        attrs = ""
        classes = "metric"
        if overview_filter:
            classes += " summary-action"
            attrs = f' data-overview-filter="{html.escape(overview_filter)}" role="button" tabindex="0" aria-pressed="false" title="Show only {html.escape(label.lower())}"'
        return f'<div class="{classes}" style="--metric-color:{color}"{attrs}><b>{html.escape(value)}</b><span>{html.escape(label)}</span></div>'

    def split_metric(label: str, left_label: str, left_value: int, right_label: str, right_value: int, color: str, overview_filter: str, left_color: str | None = None, right_color: str | None = None) -> str:
        title = f'Show only {label.lower()}'
        left_style = f' style="--half-color:{left_color}"' if left_color else ''
        right_style = f' style="--half-color:{right_color}"' if right_color else ''
        return (
            f'<div class="metric split summary-action" style="--metric-color:{color}" data-overview-filter="{html.escape(overview_filter)}" '
            f'role="button" tabindex="0" aria-pressed="false" title="{html.escape(title)}">'
            f'<div class="metric-half"{left_style}><b>{left_value}</b><span>{html.escape(left_label)}</span></div>'
            f'<div class="metric-half"{right_style}><b>{right_value}</b><span>{html.escape(right_label)}</span></div>'
            '</div>'
        )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ASVS Security Scanner - {run_id}</title>
<style>{CSS}</style>
</head><body>
<div class="shell">
  <header class="topbar">
    <div class="brand">
      <h1 data-tooltip="Application Security Verification Standard&#10;&#10;An OWASP standard that lists security requirements an application should satisfy.&#10;&#10;Covers areas like authentication, session management, access control, validation, cryptography, APIs, configuration, and logging.">ASVS Security Scanner</h1>
    </div>
    <nav class="nav">
      <button class="tab-btn" data-overview-filter="coverage">{ICONS['list']}<span>Evidence Files</span></button>
      {'<button class="tab-btn" data-tab="frcatalog">' + ICONS['shield'] + '<span>FR Catalog</span></button>' if fr_catalog_html else ''}
      {"".join(f'<button class="tab-btn" data-tab="{tid}">' + ICONS['shield'] + f'<span>{html.escape(fname)}</span></button>' for tid, fname, _ in framework_tabs_html)}
      <button class="tab-btn" data-tab="fixplan">{ICONS['doc']}<span>Agentic Fix Prompt</span></button>
    </nav>
    <div class="scan-meta">
      <table>
        <tbody>
          <tr><th>Repository</th><td>{repo_name}</td><th>Original branch</th><td>{branch}</td><th>Latest commit</th><td>{commit}</td></tr>
          <tr><th>Generated</th><td>{generated}</td><th>Safe scan branch</th><td>{safe_branch}</td><th>Report ID</th><td>{run_id}</td></tr>
        </tbody>
      </table>
    </div>
  </header>

  <section class="command-strip">
    <section class="severity-card summary-action" data-overview-filter="matrix" role="button" tabindex="0" aria-pressed="false">
      <div class="card-head"><h2>Severity Load</h2><span class="meta">matrix</span></div>
      {render_severity_panel(sev, assurance)}
    </section>
    <div class="metric-grid">
      {metric('All findings', str(total_findings), C['warn'] if total_findings else C['pass'], 'all-findings')}
      {split_metric('Critical load', 'Critical', critical_count, 'High', high_count, C['fail'] if critical_count or high_count else C['pass'], 'cves', left_color=C['critical'], right_color=C['high'])}
      {split_metric('Medium / Low', 'Medium', medium_count, 'Low', low_count, C['warn'] if medium_count or low_count else C['pass'], 'medium-low', left_color=C['medium'], right_color=C['low'])}
      {split_metric('Secrets', 'Secret Types', secret_type_count, 'Secret Files', secret_file_count, C['fail'] if secrets else C['pass'], 'secrets')}
      {metric('Manual Checklist', f'{manual_done}/{manual_total}', C['warn'] if manual_done < manual_total else C['pass'], 'manual')}
    </div>
  </section>

  <main>
    <div class="panel active" id="tab-overview">{overview_html}</div>
    {f'<div class="panel" id="tab-frcatalog">{fr_catalog_html}</div>' if fr_catalog_html else ''}
    {"".join(f'<div class="panel" id="tab-{tid}">{html_}</div>' for tid, _, html_ in framework_tabs_html)}
    <div class="panel" id="tab-fixplan">{fixplan_html}</div>
  </main>
<script type="application/json" id="reverse-lookup-data">{reverse_lookup_json}</script>
</div>

<script>
let activeOverviewFilter = null;
function setOverviewFilter(filter) {{
  const overview = document.querySelector('#tab-overview .overview-grid');
  if (!overview) return;
  const next = activeOverviewFilter === filter ? null : filter;
  activeOverviewFilter = next;
  overview.dataset.activeFilter = next || '';
  document.querySelectorAll('[data-overview-section]').forEach(section => {{
    section.hidden = Boolean(next) && section.dataset.overviewSection !== next;
  }});
  document.querySelectorAll('[data-overview-group]').forEach(group => {{
    const visibleChild = [...group.querySelectorAll('[data-overview-section]')].some(section => !section.hidden);
    group.hidden = Boolean(next) && !visibleChild;
  }});
  document.querySelectorAll('[data-overview-filter]').forEach(action => {{
    const selected = Boolean(next) && action.dataset.overviewFilter === next;
    action.classList.toggle('is-filtered', selected);
    action.setAttribute('aria-pressed', selected ? 'true' : 'false');
  }});
}}
function showPanel(tabName) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`.tab-btn[data-tab="${{tabName}}"]`);
  if (btn) btn.classList.add('active');
  document.getElementById('tab-' + tabName).classList.add('active');
  window.scrollTo({{top: 0, behavior: 'smooth'}});
}}
document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => showPanel(btn.dataset.tab));
}});
document.querySelectorAll('[data-overview-filter]').forEach(action => {{
  function activateOverviewFilter() {{
    const filter = action.dataset.overviewFilter;
    const wasActive = activeOverviewFilter === filter;
    showPanel('overview');
    if (!wasActive) setOverviewFilter(filter);
  }}
  action.addEventListener('click', activateOverviewFilter);
  action.addEventListener('keydown', event => {{
    if (event.key === 'Enter' || event.key === ' ') {{
      event.preventDefault();
      activateOverviewFilter();
    }}
  }});
}});
setOverviewFilter('matrix');
document.querySelectorAll('[data-finding-toggle]').forEach(button => {{
  button.addEventListener('click', event => {{
    event.stopPropagation();
    if (activeOverviewFilter !== 'all-findings') setOverviewFilter('all-findings');
    const row = document.getElementById(button.dataset.findingToggle);
    if (!row) return;
    const expanded = button.getAttribute('aria-expanded') === 'true';
    row.hidden = expanded;
    button.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    button.textContent = expanded ? 'Rows' : 'Rows';
  }});
}});
const evidencePreviewSource = document.getElementById('evidence-preview-data');
const evidencePreviews = evidencePreviewSource ? JSON.parse(evidencePreviewSource.textContent || '[]') : [];
function renderEvidencePreview(index) {{
  const preview = evidencePreviews[index];
  const fileEl = document.getElementById('evidence-preview-file');
  const metaEl = document.getElementById('evidence-preview-meta');
  const codeEl = document.getElementById('evidence-preview-code');
  const truncatedEl = document.getElementById('evidence-preview-truncated');
  if (!preview || !fileEl || !metaEl || !codeEl || !truncatedEl) return;
  document.querySelectorAll('[data-preview-index]').forEach(card => {{
    card.classList.toggle('is-selected', Number(card.dataset.previewIndex) === index);
  }});
  fileEl.textContent = preview.file || '-';
  metaEl.textContent = `${{preview.bytes || '-'}} · ${{preview.sha || '-'}}`;
  codeEl.textContent = '';
  const lines = String(preview.content || '').split('\\n');
  if (!lines.length || (lines.length === 1 && lines[0] === '')) {{
    const empty = document.createElement('div');
    empty.className = 'evidence-preview-empty';
    empty.textContent = 'This file is empty.';
    codeEl.appendChild(empty);
  }} else {{
    lines.forEach((line, i) => {{
      const row = document.createElement('div');
      row.className = 'evidence-line';
      const ln = document.createElement('span');
      ln.className = 'evidence-ln';
      ln.textContent = String(i + 1);
      const text = document.createElement('code');
      text.className = 'evidence-text';
      text.textContent = line || ' ';
      row.append(ln, text);
      codeEl.appendChild(row);
    }});
  }}
  truncatedEl.hidden = !preview.truncated;
}}
document.querySelectorAll('[data-preview-index]').forEach(card => {{
  card.addEventListener('click', () => renderEvidencePreview(Number(card.dataset.previewIndex)));
}});
if (evidencePreviews.length) renderEvidencePreview(0);
function setupManualChecklist() {{
  const checks = [...document.querySelectorAll('[data-manual-check]')];
  if (!checks.length) return;
  const storageKey = 'asvs-manual-checks:{run_id}';
  const scoreEl = document.getElementById('assurance-score');
  const progressEl = document.getElementById('manual-progress');
  const manualKpiValue = document.querySelector('.metric[data-overview-filter="manual"] b');
  let saved = {{}};
  try {{ saved = JSON.parse(localStorage.getItem(storageKey) || '{{}}') || {{}}; }} catch (_) {{ saved = {{}}; }}
  if (Object.keys(saved).length) {{
    checks.forEach(input => {{ input.checked = Boolean(saved[input.dataset.manualCheck]); }});
  }}
  function persist() {{
    const next = {{}};
    checks.forEach(input => {{ if (input.checked) next[input.dataset.manualCheck] = true; }});
    localStorage.setItem(storageKey, JSON.stringify(next));
  }}
  function updateManualMetrics() {{
    const total = checks.length;
    const done = checks.filter(input => input.checked).length;
    if (progressEl) progressEl.textContent = `${{done}}/${{total}}`;
    if (manualKpiValue) manualKpiValue.textContent = `${{done}}/${{total}}`;
    if (scoreEl) {{
      const autoPct = Number(scoreEl.dataset.autoPct || 0);
      const score = Math.round((0.7 * autoPct) + (0.3 * (total ? (done / total) * 100 : 0)));
      scoreEl.textContent = `${{score}}%`;
      scoreEl.dataset.manualDone = String(done);
      scoreEl.dataset.manualTotal = String(total);
      scoreEl.dataset.tooltip = `ASVS traceability score\n70% automated assurance + 30% manual evidence\n\nAutomated assurance: ${{autoPct}}%\nPASS = 1, WARN = 0.5, FAIL = 0\n\nManual evidence: ${{done}}/${{total}}\nCurrent score: round(0.7 x ${{autoPct}}% + 0.3 x manual completion)`;
    }}
  }}
  checks.forEach(input => input.addEventListener('change', () => {{ persist(); updateManualMetrics(); }}));
  document.querySelectorAll('[data-manual-select]').forEach(button => {{
    button.addEventListener('click', () => {{
      const checked = button.dataset.manualSelect === 'all';
      checks.forEach(input => {{ input.checked = checked; }});
      persist();
      updateManualMetrics();
    }});
  }});
  updateManualMetrics();
}}
setupManualChecklist();
function setupTooltips() {{
  const tooltip = document.createElement('div');
  tooltip.className = 'ui-tooltip';
  tooltip.setAttribute('role', 'tooltip');
  document.body.appendChild(tooltip);
  const placeTooltip = (event, el) => {{
    const rect = el.getBoundingClientRect();
    const sourceX = event && 'clientX' in event ? event.clientX : rect.left + rect.width / 2;
    const sourceY = event && 'clientY' in event ? event.clientY : rect.bottom;
    tooltip.style.left = '0px';
    tooltip.style.top = '0px';
    tooltip.classList.add('is-visible');
    const box = tooltip.getBoundingClientRect();
    let left = sourceX + 14;
    let top = sourceY + 16;
    if (left + box.width > window.innerWidth - 10) left = window.innerWidth - box.width - 10;
    if (top + box.height > window.innerHeight - 10) top = Math.max(10, sourceY - box.height - 18);
    tooltip.style.left = `${{Math.max(10, left)}}px`;
    tooltip.style.top = `${{Math.max(10, top)}}px`;
  }};
  const showTooltip = (event) => {{
    const el = event.currentTarget;
    const text = el.dataset.tooltip;
    if (!text) return;
    tooltip.textContent = text;
    placeTooltip(event, el);
  }};
  const hideTooltip = () => tooltip.classList.remove('is-visible');
  document.querySelectorAll('[data-tooltip]').forEach(el => {{
    const text = el.dataset.tooltip;
    if (!text) return;
    el.removeAttribute('title');
    el.classList.add('has-tooltip');
    el.addEventListener('mouseenter', showTooltip);
    el.addEventListener('mousemove', showTooltip);
    el.addEventListener('mouseleave', hideTooltip);
    el.addEventListener('focus', showTooltip);
    el.addEventListener('blur', hideTooltip);
  }});
  window.addEventListener('scroll', hideTooltip, {{ passive: true }});
}}
setupTooltips();
function setupFrCatalog() {{
  const card = document.querySelector('.fr-card');
  if (!card) return;
  const search = document.getElementById('fr-search');
  const catFilter = document.getElementById('fr-category-filter');
  const statusFilter = document.getElementById('fr-status-filter');

  // Populate category dropdown
  const cats = new Set();
  document.querySelectorAll('.fr-category-header').forEach(h => cats.add(h.dataset.category));
  [...cats].sort().forEach(c => {{
    const opt = document.createElement('option');
    opt.value = c; opt.textContent = c;
    catFilter.appendChild(opt);
  }});

  function applyFilters() {{
    const q = (search.value || '').toLowerCase();
    const cat = catFilter.value;
    const st = statusFilter.value;
    document.querySelectorAll('.fr-row').forEach(row => {{
      const rid = row.dataset.frId.toLowerCase();
      const titleCell = row.querySelector('td:nth-child(2)');
      const title = (titleCell ? titleCell.textContent : '').toLowerCase();
      const matchesSearch = !q || rid.includes(q) || title.includes(q);
      const matchesCat = !cat || row.dataset.category === cat;
      const matchesStatus = !st || row.dataset.status === st;
      const visible = matchesSearch && matchesCat && matchesStatus;
      row.classList.toggle('hidden-by-filter', !visible);
      const detail = document.querySelector('.fr-detail-row[data-fr-id="' + row.dataset.frId + '"]');
      if (detail) detail.classList.toggle('hidden-by-filter', !visible);
    }});
    // Hide category headers whose all rows are hidden
    document.querySelectorAll('.fr-category-header').forEach(h => {{
      let any = false;
      let n = h.nextElementSibling;
      while (n && !n.classList.contains('fr-category-header')) {{
        if (n.classList.contains('fr-row') && !n.classList.contains('hidden-by-filter')) {{
          any = true; break;
        }}
        n = n.nextElementSibling;
      }}
      h.classList.toggle('hidden-by-filter', !any);
    }});
  }}

  [search].forEach(el => el.addEventListener('input', applyFilters));
  [catFilter, statusFilter].forEach(el => el.addEventListener('change', applyFilters));

  // Click row to expand detail
  document.querySelectorAll('.fr-row').forEach(row => {{
    row.addEventListener('click', () => {{
      const detail = document.querySelector('.fr-detail-row[data-fr-id="' + row.dataset.frId + '"]');
      if (!detail) return;
      const isHidden = detail.hasAttribute('hidden');
      if (isHidden) detail.removeAttribute('hidden'); else detail.setAttribute('hidden', '');
      row.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
    }});
    row.addEventListener('keydown', e => {{
      if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); row.click(); }}
    }});
  }});
}}
setupFrCatalog();
function setupFrameworkTabs() {{
  document.querySelectorAll('[id^="tab-fw-"]').forEach(panel => {{
    const card = panel.querySelector('.fw-card');
    if (!card) return;
    const prefix = card.querySelector('[id$="-search"]')?.id.replace('-search', '') || '';
    const search = document.getElementById(prefix + '-search');
    const groupFilter = document.getElementById(prefix + '-chapter-filter');
    const statusFilter = document.getElementById(prefix + '-status-filter');
    const showFiltered = document.getElementById(prefix + '-show-filtered');
    if (!search) return;

    // Populate group dropdown
    const groups = new Set();
    panel.querySelectorAll('.fw-group-header').forEach(h => groups.add(h.dataset.group));
    [...groups].sort().forEach(g => {{
      const opt = document.createElement('option');
      opt.value = g; opt.textContent = g;
      groupFilter.appendChild(opt);
    }});

    function applyFilters() {{
      const q = (search.value || '').toLowerCase();
      const grp = groupFilter.value;
      const st = statusFilter.value;
      const showF = showFiltered?.checked || false;
      panel.querySelectorAll('.fw-row').forEach(row => {{
        if (row.classList.contains('fw-row-filtered') && !showF) {{
          row.classList.add('hidden-by-filter');
          return;
        }}
        const rid = row.dataset.rowId.toLowerCase();
        const desc = row.querySelector('td:nth-child(4)')?.textContent.toLowerCase() || '';
        const matchesSearch = !q || rid.includes(q) || desc.includes(q);
        const matchesGroup = !grp || row.dataset.group === grp;
        const matchesStatus = !st || row.dataset.state === st;
        const visible = matchesSearch && matchesGroup && matchesStatus;
        row.classList.toggle('hidden-by-filter', !visible);
        const detail = panel.querySelector('.fw-detail-row[data-row-id="' + row.dataset.rowId + '"]');
        if (detail) detail.classList.toggle('hidden-by-filter', !visible);
      }});
      panel.querySelectorAll('.fw-group-header').forEach(h => {{
        let any = false;
        let n = h.nextElementSibling;
        while (n && !n.classList.contains('fw-group-header')) {{
          if (n.classList.contains('fw-row') && !n.classList.contains('hidden-by-filter')) {{ any = true; break; }}
          n = n.nextElementSibling;
        }}
        h.classList.toggle('hidden-by-filter', !any);
      }});
    }}

    [search, showFiltered].forEach(el => el?.addEventListener('input', applyFilters));
    [groupFilter, statusFilter].forEach(el => el?.addEventListener('change', applyFilters));

    panel.querySelectorAll('.fw-row').forEach(row => {{
      row.addEventListener('click', () => {{
        const detail = panel.querySelector('.fw-detail-row[data-row-id="' + row.dataset.rowId + '"]');
        if (!detail) return;
        const isHidden = detail.hasAttribute('hidden');
        if (isHidden) detail.removeAttribute('hidden'); else detail.setAttribute('hidden', '');
        row.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
      }});
      row.addEventListener('keydown', e => {{
        if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); row.click(); }}
      }});
    }});
  }});
}}
setupFrameworkTabs();
function setupReverseLookup() {{
  const dataEl = document.getElementById('reverse-lookup-data');
  if (!dataEl) return;
  let lookup;
  try {{ lookup = new Map(JSON.parse(dataEl.textContent || '[]')); }} catch (_) {{ return; }}
  if (!lookup.size) return;

  // For each scanner name, build a list of [pattern, entry] pairs
  const byScanner = {{}};
  for (const [ref, entry] of lookup) {{
    const colonIdx = ref.indexOf(':');
    if (colonIdx < 0) continue;
    const scanner = ref.substring(0, colonIdx);
    const pattern = ref.substring(colonIdx + 1);
    if (!byScanner[scanner]) byScanner[scanner] = [];
    byScanner[scanner].push([pattern, entry]);
  }}

  // Simple glob matcher (no regex — avoids f-string brace conflicts)
  function globMatch(str, pat) {{
    if (pat === '*') return true;
    if (pat.indexOf('*') < 0) return str === pat;
    const parts = pat.split('*');
    let idx = 0;
    for (let i = 0; i < parts.length; i++) {{
      if (parts[i] === '') continue;
      idx = str.indexOf(parts[i], idx);
      if (idx < 0) return false;
      if (i === 0 && idx > 0) return false; // prefix must match start
      idx += parts[i].length;
    }}
    // If last part non-empty, must match end
    const last = parts[parts.length - 1];
    if (last && idx !== str.length) return false;
    return true;
  }}

  // Scan All Findings table rows for scanner rule_ids
  const findingTables = document.querySelectorAll('.finding-detail');
  findingTables.forEach(table => {{
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {{
      const cells = row.querySelectorAll('td');
      if (cells.length < 3) return;
      // Try to extract rule_id from the second cell (usually contains a <code> with the ID)
      const codeEl = cells[1].querySelector('code') || cells[0].querySelector('code');
      if (!codeEl) return;
      const ruleId = codeEl.textContent.trim();

      // Try each scanner's patterns
      let matchedEntry = null;
      for (const [scanner, patterns] of Object.entries(byScanner)) {{
        for (const [pattern, entry] of patterns) {{
          if (globMatch(ruleId, pattern)) {{
            matchedEntry = entry;
            break;
          }}
        }}
        if (matchedEntry) break;
      }}

      if (matchedEntry && matchedEntry.compliance_rows.length > 0) {{
        // Add impact badge to the last cell
        const lastCell = cells[cells.length - 1];
        const fwSet = new Set(matchedEntry.compliance_rows.map(r => r.framework));
        const fwList = [...fwSet].join(', ');
        const btn = document.createElement('button');
        btn.className = 'asvs-impact-btn';
        btn.textContent = `ASVS impact (${{matchedEntry.compliance_rows.length}})`;
        btn.title = `Threatens ${{matchedEntry.compliance_rows.length}} compliance row(s) via ${{matchedEntry.fr_ids.join(', ')}}`;
        btn.dataset.frIds = JSON.stringify(matchedEntry.fr_ids);
        btn.dataset.rows = JSON.stringify(matchedEntry.compliance_rows);
        btn.addEventListener('click', (e) => {{
          e.stopPropagation();
          const rows = matchedEntry.compliance_rows;
          const fw = rows[0].framework;
          const tabId = 'fw-' + fw.toLowerCase().replace(/[-_]/g, '');
          // Switch to framework tab
          const btn2 = document.querySelector(`.tab-btn[data-tab="${{tabId}}"]`);
          if (btn2) btn2.click();
          // Highlight the affected rows
          setTimeout(() => {{
            const panel = document.getElementById('tab-' + tabId);
            if (!panel) return;
            const rowIds = new Set(rows.map(r => r.row));
            panel.querySelectorAll('.fw-row').forEach(r => {{
              if (rowIds.has(r.dataset.rowId)) {{
                r.style.outline = '2px solid #ff4d6d';
                r.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
              }}
            }});
          }}, 100);
        }});
        lastCell.appendChild(document.createElement('br'));
        lastCell.appendChild(btn);
      }}
    }});
  }});
}}
setupReverseLookup();
function copyPrompt() {{
  const btn = document.querySelector('.copy-btn');
  const label = btn.querySelector('.btn-label');
  const original = label.textContent;
  const text = document.getElementById('prompt-body').innerText;
  const done = () => {{ label.textContent = 'Copied'; btn.classList.add('copied'); setTimeout(() => {{ label.textContent = original; btn.classList.remove('copied'); }}, 1600); }};
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(done).catch(fallback);
  else fallback();
  function fallback() {{ const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done(); }}
}}
</script>
</body></html>
"""

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-dir", required=True)
    ap.add_argument("--fr-catalog", default=None,
                    help="Path to project FR catalog JSON (enables FR-driven view)")
    ap.add_argument("--junit-xml", default=None,
                    help="Path to JUnit XML test results (may be repeated for multi-runner)")
    args = ap.parse_args()
    report_dir = Path(args.report_dir)
    out = report_dir / "dashboard.html"
    out.write_text(render(report_dir=report_dir,
                          fr_catalog_path=args.fr_catalog,
                          junit_xml_path=args.junit_xml))
    print(f"dashboard: written to {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
