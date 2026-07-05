#!/usr/bin/env python3
"""Scanner output parsers, constants, and dashboard utility functions.

Extracted from generate_dashboard.py. Contains all non-rendering code:
- Constants: C (palette), SEVERITY_COLORS, STATUS_COLORS, SEVERITY_ORDER
- Utilities: load_json, short_text, location_label, output_candidates
- Scanner parsers: semgrep/gitleaks/trivy/grype/syft detail rows
- Severity aggregation: severity_issues, critical_high_issues, etc.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

C = {
    "bg":         "#12171b",
    "surface":    "#1b2329",
    "border":     "#34434c",
    "border_strong":"#4a5c66",
    "ink":        "#f2f7f5",
    "ink_2":      "#d2dfda",
    "ink_3":      "#a4b4ae",
    "ink_4":      "#7b8b85",
    "primary":    "#56c7b7",
    "primary_2":  "#8fcbe8",
    "primary_bg": "#173334",

    "critical":   "#ff4d6d",
    "high":       "#ff8a3d",
    "medium":     "#ffd166",
    "low":        "#2dd4bf",
    "unknown":    "#718096",

    "pass":       "#35d07f",
    "warn":       "#ffd166",
    "fail":       "#ff4d6d",
    "skipped":    "#718096",
}
SEVERITY_COLORS = {
    "CRITICAL": C["critical"], "HIGH": C["high"], "MEDIUM": C["medium"],
    "LOW": C["low"], "UNKNOWN": C["unknown"],
}
STATUS_COLORS = {"PASS": C["pass"], "WARN": C["warn"], "FAIL": C["fail"], "SKIPPED": C["skipped"]}
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]

SCANNERS = {
    # Level 1
    "semgrep": {
        "title": "Semgrep",
        "level": 1,
        "category": "Static Analysis (SAST)",
        "purpose": "Scans source code for security anti-patterns, injection risks, and insecure APIs. Catches XSS sinks, SQL injection, weak crypto, and dangerous deserializer usage via community-maintained rules.",
        "icon": "code",
        "output": "reports/semgrep.sarif",
    },
    "gitleaks": {
        "title": "Gitleaks",
        "level": 1,
        "category": "Secret Detection",
        "purpose": "Inspects every file for accidentally-committed credentials: API keys, AWS tokens, private keys, OAuth tokens, database URLs, and more. Catches secrets before they reach production.",
        "icon": "key",
        "output": "reports/gitleaks.json",
    },
    "trivy-fs": {
        "title": "Trivy Filesystem",
        "level": 1,
        "category": "Dependency Vulnerabilities",
        "purpose": "Walks the project tree (including node_modules) to detect known-vulnerable npm, pip, maven, Go, and OS packages. The authoritative source for filesystem-level dependency CVEs.",
        "icon": "package",
        "output": "reports/trivy-fs.json",
    },
    "trivy-config": {
        "title": "Trivy Config",
        "level": 1,
        "category": "IaC Misconfiguration",
        "purpose": "Checks Dockerfiles, Kubernetes manifests, Terraform, and CloudFormation against hardening rules: non-root user, healthcheck present, no exposed Docker socket, no privileged containers.",
        "icon": "settings",
        "output": "reports/trivy-config.json",
    },
    "syft": {
        "title": "Syft",
        "level": 1,
        "category": "SBOM Generation",
        "purpose": "Produces a CycloneDX Software Bill of Materials enumerating every component in the project. Foundation for license compliance, dependency traceability, and supply-chain assurance.",
        "icon": "list",
        "output": "sbom/sbom.cyclonedx.json",
    },
    "grype": {
        "title": "Grype",
        "level": 1,
        "category": "Vulnerability Matching",
        "purpose": "Matches the SBOM against the Grype vulnerability database (NVD + GitHub Advisables + vendor feeds) for fast, deterministic CVE lookup. Pairs with Syft for SBOM-driven scanning.",
        "icon": "shield",
        "output": "reports/grype.json",
    },
    "osv-scanner": {
        "title": "osv-scanner",
        "level": 1,
        "category": "Open-Source Vulnerabilities",
        "purpose": "Queries OSV.dev (Google's free vulnerability database) for npm, PyPI, Maven, Go, and Cargo packages. Requires lockfiles (package-lock.json, yarn.lock, pnpm-lock.yaml) for accurate coverage.",
        "icon": "globe",
        "output": "reports/osv-scanner.json",
    },
    # Level 2 — image
    "trivy-image": {
        "title": "Trivy Image",
        "level": 2,
        "category": "Container Image Scan",
        "purpose": "Scans a built Docker image for OS package vulnerabilities and config issues. Run after build, before release.",
        "icon": "container",
        "output": "reports/trivy-image.json",
    },
    "syft-image": {
        "title": "Syft Image",
        "level": 2,
        "category": "Image SBOM",
        "purpose": "Produces a CycloneDX SBOM for a built Docker image. Used to attest what's actually shipping in the release artifact.",
        "icon": "list",
        "output": "sbom/image-sbom.cyclonedx.json",
    },
    "grype-image": {
        "title": "Grype Image",
        "level": 2,
        "category": "Image Vulnerability Matching",
        "purpose": "Matches the image SBOM against the Grype database for OS-package and library CVEs in the built artifact.",
        "icon": "shield",
        "output": "reports/grype-image.json",
    },
    # Level 2 — runtime
    "zap-baseline": {
        "title": "OWASP ZAP Baseline",
        "level": 2,
        "category": "Active Web App Scan",
        "purpose": "Passive web application security scan against a running URL. Catches common web vulns: missing headers, exposed admin paths, info leakage.",
        "icon": "bug",
        "output": "reports/zap-baseline.json",
    },
    "security-headers": {
        "title": "Security Headers",
        "level": 2,
        "category": "HTTP Header Audit",
        "purpose": "Inspects HTTP response headers against best practice: HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy.",
        "icon": "lock",
        "output": "reports/security-headers.json",
    },
    "testssl": {
        "title": "testssl.sh",
        "level": 2,
        "category": "TLS Configuration Audit",
        "purpose": "Audits the TLS configuration of an HTTPS endpoint: protocol versions, cipher suites, certificate chain, OCSP stapling, known weaknesses (Heartbleed, POODLE).",
        "icon": "lock",
        "output": "reports/testssl.jsonl",
    },
    "clamav": {
        "title": "ClamAV",
        "level": 2,
        "category": "Malware Scan",
        "purpose": "Signature-based malware scan on uploaded files. Use against user-uploaded content directories before serving.",
        "icon": "alert",
        "output": "reports/clamav.txt",
    },
}


ICONS = {
    "code":      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
    "key":       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>',
    "package":   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="16.5" y1="9.4" x2="7.5" y2="4.21"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>',
    "settings":  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01A1.65 1.65 0 0 0 9 4.6V4a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    "list":      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>',
    "shield":    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    "globe":     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    "container": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12L12 22 2 12l10-10 10 10z"/><path d="M6 12h12"/></svg>',
    "bug":       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="6" width="8" height="14" rx="4"/><path d="M19 7l-3 2M5 7l3 2M19 13h-3M8 13H5M19 19l-3-2M5 19l3-2M12 6V4"/></svg>',
    "lock":      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    "alert":     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    "copy":      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
    "check":     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    "user":      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="7" r="4"/></svg>',
    "doc":       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    "filter":    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>',
}


PREVIEW_MAX_BYTES = 220_000
PREVIEW_MAX_LINES = 900


def load_json(p: Path):
    try:
        if p.exists() and p.stat().st_size > 0:
            return json.loads(p.read_text(errors="replace"))
    except Exception:
        return None
    return None


def aggregate_severity(findings: dict) -> dict:
    out = {s: 0 for s in SEVERITY_ORDER}
    for v in findings.values():
        if isinstance(v, dict):
            for s in SEVERITY_ORDER:
                out[s] += v.get(s, 0)
        elif isinstance(v, int) and v > 0:
            out["CRITICAL"] += v
    return out


def top_grype(grype_path: Path, limit: int = 12) -> list[dict]:
    data = load_json(grype_path)
    if not data:
        return []
    out = []
    for m in data.get("matches", []) or []:
        v = m.get("vulnerability") or {}
        a = m.get("artifact") or {}
        out.append({
            "id": v.get("id", "?"),
            "severity": (v.get("severity") or "UNKNOWN").upper(),
            "pkg": a.get("name", "?"),
            "version": a.get("version", "?"),
            "fixed_in": ", ".join((v.get("fix") or {}).get("versions") or []) or "—",
        })
    rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}
    out.sort(key=lambda x: rank.get(x["severity"], 99))
    return out[:limit]


def secret_breakdowns(gitleaks_path: Path):
    data = load_json(gitleaks_path)
    if not isinstance(data, list):
        return [], [], 0
    by_rule: Counter = Counter(f.get("RuleID", "?") for f in data)
    by_file: Counter = Counter(f.get("File", "?") for f in data)
    return by_rule.most_common(10), by_file.most_common(10), len(data)


def top_packages(grype_path: Path, limit: int = 10) -> list[tuple[str, int]]:
    data = load_json(grype_path)
    if not data:
        return []
    pkgs: Counter = Counter()
    for m in data.get("matches", []) or []:
        name = (m.get("artifact") or {}).get("name", "?")
        pkgs[name] += 1
    return pkgs.most_common(limit)


def parse_ignored_from_log(run_log: Path) -> dict[str, dict]:
    """Extract 'apply-scannerignore' lines from run.log.

    Returns {scanner_name: {removed, before, after, patterns_count}}.
    """
    out: dict[str, dict] = {}
    if not run_log.exists():
        return out
    pattern = re.compile(
        r"apply-scannerignore \[([^\]]+)\]: removed (\d+) of (\d+) findings \((\d+) kept\) using (\d+) patterns"
    )
    for line in run_log.read_text(errors="replace").splitlines():
        m = pattern.search(line)
        if m:
            scanner, removed, before, after, n_pat = m.groups()
            out[scanner] = {
                "removed": int(removed),
                "before": int(before),
                "after": int(after),
                "patterns_count": int(n_pat),
            }
    return out


def parse_scannerignore_patterns(scannerignore: Path) -> list[str]:
    if not scannerignore.exists():
        return []
    patterns = []
    for raw in scannerignore.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


# ===========================================================================
# Charts
# ===========================================================================

def donut_chart(slices: list[tuple[str, int, str]], *, size: int = 180, thickness: int = 26,
                center_value: str = "", center_label: str = "", gradient_id: str = None) -> str:
    """Donut with optional gradient stroke per slice. Animated on load."""
    total = sum(v for _, v, _ in slices) or 1
    radius = (size - thickness) // 2
    cx = cy = size // 2
    circumference = 2 * 3.14159265358979 * radius
    offset = 0.0
    arcs = []
    legend = []
    gid = gradient_id or f"g-{abs(hash(tuple(slices)))}"
    for i, (label, value, color) in enumerate(slices):
        if value <= 0:
            continue
        portion = value / total
        length = portion * circumference
        # gradient stop per slice for "pop"
        grad_id = f"{gid}-{i}"
        lighter = _lighten(color, 0.18)
        arcs.append(
            f'<defs><linearGradient id="{grad_id}" x1="0%" y1="0%" x2="100%" y2="100%">'
            f'<stop offset="0%" stop-color="{lighter}"/>'
            f'<stop offset="100%" stop-color="{color}"/>'
            f'</linearGradient></defs>'
            f'<circle class="donut-arc" cx="{cx}" cy="{cy}" r="{radius}" fill="none" '
            f'stroke="url(#{grad_id})" stroke-width="{thickness}" '
            f'stroke-dasharray="0 {circumference:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})" '
            f'data-target-len="{length:.2f}" data-target-gap="{circumference - length:.2f}"/>'
        )
        legend.append(
            f'<div class="legend-item"><span class="legend-swatch" style="background:linear-gradient(135deg,{lighter},{color})"></span>'
            f'<span class="legend-label">{html.escape(label)}</span>'
            f'<span class="legend-value">{value}</span></div>'
        )
        offset += length
    center_svg = ""
    if center_value:
        center_svg = (
            f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-size="32" font-weight="700" fill="{C["ink"]}">{html.escape(center_value)}</text>'
            f'<text x="{cx}" y="{cy + 20}" text-anchor="middle" font-size="10" fill="{C["ink_3"]}" letter-spacing="0.08em">{html.escape(center_label.upper())}</text>'
        )
    return (
        f'<div class="chart-with-legend">'
        f'<div class="donut-wrap"><svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">{"".join(arcs)}{center_svg}</svg></div>'
        f'<div class="legend">{"".join(legend)}</div>'
        f'</div>'
    )


def gauge_chart(value_pct: int, *, color: str, label: str, subtitle: str = "", size: int = 200) -> str:
    pct = max(0, min(100, value_pct))
    radius = size // 2 - 18
    cx = size // 2
    cy = size // 2
    semi = 3.14159265358979 * radius
    fill_len = (pct / 100) * semi
    gid = f"gauge-{abs(hash((label, color, pct)))}"
    lighter = _lighten(color, 0.2)
    return (
        f'<div class="gauge-wrap">'
        f'<svg width="{size}" height="{size // 2 + 40}" viewBox="0 0 {size} {size // 2 + 40}">'
        f'<defs><linearGradient id="{gid}" x1="0%" y1="0%" x2="100%" y2="0%">'
        f'<stop offset="0%" stop-color="{lighter}"/>'
        f'<stop offset="100%" stop-color="{color}"/>'
        f'</linearGradient></defs>'
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{C["border"]}" stroke-width="14" '
        f'stroke-linecap="round" stroke-dasharray="{semi:.2f} {semi:.2f}" transform="rotate(-90 {cx} {cy})" />'
        f'<circle class="gauge-arc" cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="url(#{gid})" stroke-width="14" '
        f'stroke-linecap="round" stroke-dasharray="0 {semi:.2f}" '
        f'data-target-len="{fill_len:.2f}" data-target-gap="{semi:.2f}" '
        f'transform="rotate(-90 {cx} {cy})" />'
        f'<text x="{cx}" y="{cy - 8}" text-anchor="middle" font-size="36" font-weight="700" fill="{C["ink"]}">{pct}<tspan font-size="18" fill="{C["ink_3"]}">%</tspan></text>'
        f'<text x="{cx}" y="{cy + 18}" text-anchor="middle" font-size="11" fill="{C["ink_3"]}" letter-spacing="0.08em">{html.escape(label.upper())}</text>'
        f'</svg>'
        f'{f"<div class=\"gauge-subtitle\">{html.escape(subtitle)}</div>" if subtitle else ""}'
        f'</div>'
    )


def hbar_chart(items: list[tuple[str, int]], *, color: str = None, max_value: int = None,
               animate: bool = True) -> str:
    if not items:
        return '<p class="empty-state">No data.</p>'
    if max_value is None:
        max_value = max(v for _, v in items) or 1
    rows = []
    for i, (label, value) in enumerate(items):
        width_pct = (value / max_value) * 100 if max_value else 0
        anim_class = " bar-fill-anim" if animate else ""
        rows.append(
            f'<div class="bar-row">'
            f'<div class="bar-label" title="{html.escape(label)}"><code>{html.escape(label)}</code></div>'
            f'<div class="bar-track"><div class="bar-fill{anim_class}" data-target-pct="{width_pct:.1f}" style="background:linear-gradient(90deg,{_lighten(color or C["primary"], 0.15)},{color or C["primary"]})"></div></div>'
            f'<div class="bar-value">{value}</div>'
            f'</div>'
        )
    return f'<div class="bar-chart">{"".join(rows)}</div>'


def _lighten(hex_color: str, amount: float) -> str:
    """Mix hex color with white by `amount` (0..1)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = int(r + (255 - r) * amount)
    g = int(g + (255 - g) * amount)
    b = int(b + (255 - b) * amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def status_pill(status: str) -> str:
    color = STATUS_COLORS.get(status, C["unknown"])
    return f'<span class="pill" style="--c:{color}">{status}</span>'


def sev_badge(sev: str) -> str:
    color = SEVERITY_COLORS.get(sev, C["unknown"])
    return f'<span class="sev" style="background:{color}">{html.escape(sev)}</span>'


def icon_span(name: str, *, size: int = 20, color: str = "currentColor") -> str:
    svg = ICONS.get(name, ICONS["shield"])
    return f'<span class="icon" style="width:{size}px;height:{size}px;color:{color}">{svg}</span>'


# ===========================================================================
# Minimal markdown renderer (for the agent prompt)
# ===========================================================================

def inline_md(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out = []
    in_code = False
    code_buf: list[str] = []
    in_list = False
    list_type = None
    table_buf: list[list[str]] = []

    def close_list():
        nonlocal in_list, list_type
        if in_list:
            out.append(f"</{list_type}>")
            in_list = False
            list_type = None

    def flush_table():
        nonlocal table_buf
        if not table_buf:
            return
        out.append('<div class="md-table-wrap"><table class="md-table">')
        out.append("<thead><tr>" + "".join(f"<th>{inline_md(c)}</th>" for c in table_buf[0]) + "</tr></thead>")
        out.append("<tbody>")
        for row in table_buf[1:]:
            out.append("<tr>" + "".join(f"<td>{inline_md(c)}</td>" for c in row) + "</tr>")
        out.append("</tbody></table></div>")
        table_buf = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                out.append('<pre class="md-code"><code>' + "\n".join(html.escape(l) for l in code_buf) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                close_list(); flush_table()
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            close_list()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            table_buf.append(cells)
            continue
        elif table_buf:
            flush_table()
        if stripped.startswith("### "):
            close_list(); out.append(f"<h4>{inline_md(stripped[4:])}</h4>")
        elif stripped.startswith("## "):
            close_list(); out.append(f"<h3>{inline_md(stripped[3:])}</h3>")
        elif stripped.startswith("# "):
            close_list(); out.append(f"<h2>{inline_md(stripped[2:])}</h2>")
        elif stripped == "---":
            close_list(); out.append("<hr>")
        elif stripped.startswith("> "):
            close_list(); out.append(f"<blockquote>{inline_md(stripped[2:])}</blockquote>")
        elif re.match(r"^\d+\.\s", stripped):
            if list_type != "ol":
                close_list(); out.append("<ol>"); in_list = True; list_type = "ol"
            out.append(f"<li>{inline_md(re.sub(r'^\d+\.\s', '', stripped))}</li>")
        elif stripped.startswith("- "):
            if list_type != "ul":
                close_list(); out.append("<ul>"); in_list = True; list_type = "ul"
            out.append(f"<li>{inline_md(stripped[2:])}</li>")
        elif stripped == "":
            close_list()
        else:
            close_list(); out.append(f"<p>{inline_md(stripped)}</p>")

    if in_code:
        out.append('<pre class="md-code"><code>' + "\n".join(html.escape(l) for l in code_buf) + "</code></pre>")
    close_list(); flush_table()
    return "\n".join(out)


# ===========================================================================
# CSS
# ===========================================================================

CSS = """
:root {
  color-scheme: dark;
  --bg: #12171b; --surface: #1b2329; --surface-2: #222b32; --ink: #f2f7f5;
  --ink-2: #d2dfda; --ink-3: #a4b4ae; --muted: #7b8b85; --line: #34434c;
  --line-strong: #4a5c66; --primary: #56c7b7; --primary-2: #8fcbe8; --primary-bg: #173334;
  --critical: #ff4d6d; --high: #ff8a3d; --medium: #ffd166; --low: #2dd4bf; --unknown: #718096;
  --pass: #35d07f; --warn: #ffd166; --fail: #ff4d6d; --skipped: #718096;
  --radius: 8px; --mono: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
  --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --shadow: 0 14px 34px rgba(0,0,0,.24), 0 0 0 1px rgba(143,203,232,.06);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; background:var(--bg); }
body {
  margin:0; min-height:100vh; color:var(--ink); font-family:var(--sans); font-size:13px; line-height:1.38;
  background:
    linear-gradient(180deg, rgba(86,199,183,.08), transparent 300px),
    radial-gradient(circle at 18% -10%, rgba(143,203,232,.13), transparent 34%),
    radial-gradient(circle at 86% 4%, rgba(255,77,109,.06), transparent 30%),
    var(--bg);
  -webkit-font-smoothing:antialiased;
}
button, input { font: inherit; }
.shell { max-width: 1440px; margin: 0 auto; padding: 18px 22px 42px; }
.topbar { display:grid; grid-template-columns: minmax(320px, 1fr) auto; gap:14px 18px; align-items:start; padding: 12px 0 14px; border-bottom:1px solid var(--line-strong); }
.brand h1 { display:inline-block; width:auto; margin:0; font-size: clamp(24px, 3.2vw, 42px); line-height:.95; letter-spacing:0; font-weight:850; color:var(--ink); text-shadow:0 0 28px rgba(51,214,189,.12); }
.brand .sub { margin-top:8px; color:var(--ink-3); font-size:12px; max-width:900px; }
.scan-meta { grid-column:1 / -1; width:100%; border:1px solid var(--line); border-radius:var(--radius); overflow:hidden; background:rgba(27,35,41,.78); box-shadow:inset 0 1px 0 rgba(255,255,255,.04); }
.scan-meta table { width:100%; border-collapse:collapse; table-layout:fixed; }
.scan-meta th, .scan-meta td { padding:8px 10px; border-right:1px solid var(--line); vertical-align:top; text-align:left; }
.scan-meta th:last-child, .scan-meta td:last-child { border-right:0; }
.scan-meta th { width:16%; color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.06em; background:#202930; }
.scan-meta td { color:var(--ink-2); font-family:var(--mono); font-size:11px; overflow-wrap:anywhere; }
code { font-family:var(--mono); font-size:11px; background:#183236; color:#baf4ea; border:1px solid rgba(86,199,183,.24); border-radius:5px; padding:1px 5px; }
.command-strip { position:sticky; top:8px; z-index:20; margin:14px 0 16px; display:grid; grid-template-columns: minmax(340px,.9fr) minmax(620px,1.6fr); gap:10px; align-items:stretch; background:transparent; padding:0; }
.severity-card { background:linear-gradient(180deg, rgba(34,43,50,.98), rgba(27,35,41,.98)); border:1px solid var(--line); border-radius:var(--radius); box-shadow:0 1px 0 rgba(255,255,255,.03), 0 10px 20px rgba(0,0,0,.14); overflow:hidden; }
.severity-card .card-head { min-height:34px; padding:8px 10px; }
.severity-card .risk-rail { padding:9px 10px 10px; }
.summary-action { cursor:pointer; transition:border-color .15s, box-shadow .15s, transform .15s; }
.summary-action:hover { border-color:#5f7882; transform:translateY(-1px); }
.summary-action:focus-visible { outline:2px solid var(--primary); outline-offset:2px; }
.summary-action.is-filtered { border-color:var(--primary); box-shadow:0 0 0 1px rgba(86,199,183,.20), 0 10px 22px rgba(86,199,183,.10); }
[hidden] { display:none !important; }
.metric-grid { display:grid; grid-template-columns: repeat(5, minmax(92px,1fr)); gap:8px; }
.metric { background:linear-gradient(180deg, rgba(34,43,50,.98), rgba(27,35,41,.98)); border:1px solid var(--line); border-radius:var(--radius); padding:10px 11px; min-height:82px; box-shadow:0 1px 0 rgba(255,255,255,.03), 0 10px 20px rgba(0,0,0,.14); }
.metric b { display:block; font-size:26px; line-height:1; font-variant-numeric: tabular-nums; color:var(--metric-color,var(--ink)); text-shadow:0 0 10px color-mix(in srgb, var(--metric-color,var(--ink)) 18%, transparent); }
.metric span { display:block; margin-top:6px; font-size:10px; line-height:1.15; text-transform:uppercase; letter-spacing:.07em; color:var(--ink-3); }
.metric.split { padding:0; display:grid; grid-template-rows:1fr 1fr; overflow:hidden; }
.metric-half { min-width:0; padding:8px 11px; display:flex; flex-direction:column; justify-content:center; }
.metric-half + .metric-half { border-top:1px solid var(--line); }
.metric-half b { font-size:22px; color:var(--half-color, var(--metric-color,var(--ink))); text-shadow:0 0 10px color-mix(in srgb, var(--half-color, var(--metric-color,var(--ink))) 18%, transparent); }
.metric-half span { white-space:normal; color:color-mix(in srgb, var(--half-color, var(--ink-3)) 68%, var(--ink-3)); }
.nav { display:flex; gap:6px; align-items:stretch; justify-self:end; }
.tab-btn { border:1px solid var(--line); background:linear-gradient(180deg,#222b32,#1b2329); color:var(--ink-2); border-radius:var(--radius); padding:0 12px; min-width:82px; height:38px; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:7px; font-size:12px; font-weight:700; box-shadow:0 1px 0 rgba(255,255,255,.03); }
.tab-btn:hover { border-color:#5a6d77; color:var(--ink); }
.tab-btn svg { width:15px; height:15px; }
.tab-btn.active { background:linear-gradient(180deg,#2c8177,#22665f); border-color:#56c7b7; color:#f7fffc; box-shadow:0 0 0 1px rgba(86,199,183,.16), 0 10px 22px rgba(86,199,183,.10); }
.count { min-width:18px; height:18px; padding:0 5px; border-radius:999px; display:inline-flex; align-items:center; justify-content:center; background:rgba(255,255,255,.14); color:inherit; font-size:10px; }
.has-tooltip { cursor:help; }
.ui-tooltip { position:fixed; z-index:1000; max-width:min(460px, calc(100vw - 28px)); padding:10px 12px; border:1px solid rgba(86,199,183,.45); border-radius:7px; background:#eefaf7; color:#122026; box-shadow:0 16px 44px rgba(0,0,0,.38); font-size:12px; line-height:1.45; font-weight:650; pointer-events:none; opacity:0; transform:translateY(4px); transition:opacity .08s ease, transform .08s ease; overflow-wrap:anywhere; white-space:pre-line; }
.ui-tooltip.is-visible { opacity:1; transform:translateY(0); }
.ui-tooltip::before { content:''; position:absolute; left:14px; top:-6px; width:10px; height:10px; transform:rotate(45deg); background:#eefaf7; border-left:1px solid rgba(86,199,183,.45); border-top:1px solid rgba(86,199,183,.45); }
.panel { display:none; }
.panel.active { display:block; }
.overview-grid { display:grid; gap:14px; align-items:start; }
.stack { display:grid; gap:14px; }
.card { background:linear-gradient(180deg, rgba(27,35,41,.98), rgba(23,30,35,.98)); border:1px solid var(--line); border-radius:var(--radius); box-shadow:0 1px 0 rgba(255,255,255,.03), 0 12px 28px rgba(0,0,0,.16); overflow:hidden; }
.card-head { min-height:40px; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 12px; border-bottom:1px solid var(--line); background:linear-gradient(180deg,#26313a,#202a31); }
.card-head h2, .card-head h3 { margin:0; font-size:12px; text-transform:uppercase; letter-spacing:.07em; color:var(--ink-2); }
.card-head .meta { color:var(--muted); font-size:11px; }
.matrix { width:100%; border-collapse:collapse; table-layout:fixed; }
.matrix th, .matrix td { padding:7px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; }
.matrix th { font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); background:#202930; font-weight:800; }
.matrix tr:last-child td { border-bottom:0; }
.matrix tbody tr:hover { background:#243039; }
.matrix tr.category-row td {
  background:linear-gradient(90deg, rgba(86,199,183,.18), #26333c 34%, #222b32);
  color:var(--ink); font-size:11px; text-transform:uppercase; letter-spacing:.09em; font-weight:950;
  border-top:2px solid color-mix(in srgb, var(--primary) 58%, var(--line));
  border-bottom:1px solid var(--line-strong); padding:11px 12px;
  box-shadow:inset 4px 0 0 var(--primary), inset 0 1px 0 rgba(255,255,255,.04);
}
.matrix tr.category-row:first-child td { border-top:0; }
.matrix tr.category-row .category-meta {
  color:#b8c6c1; font-weight:750; margin-left:10px; padding-left:10px;
  border-left:1px solid rgba(184,198,193,.32); text-transform:none; letter-spacing:0;
}
.matrix tr.category-row:hover td { background:linear-gradient(90deg, rgba(86,199,183,.20), #26333c 34%, #222b32); }
.matrix .scanner { width: 172px; font-weight:800; color:var(--ink); }
.matrix .level { width:44px; color:var(--muted); font-family:var(--mono); font-size:11px; }
.matrix .status-col { width:86px; }
.matrix .findings-col { width:168px; }
.matrix .evidence-col { width:180px; }
.reason { color:var(--ink-3); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.finding-parent td { background:#1e282f; border-bottom:0; }
.overview-grid:not([data-active-filter="all-findings"]) .finding-detail-row { display:none; }
.finding-detail-row td { padding:0 8px 12px; background:#172025; border-bottom:1px solid var(--line-strong); }
.finding-action { width:86px; text-align:right; }
.finding-toggle { height:24px; padding:0 8px 0 6px; border-radius:999px; border:1px solid rgba(86,199,183,.18); background:rgba(86,199,183,.055); color:#b9d8d2; font-size:11px; font-weight:750; text-transform:none; letter-spacing:0; cursor:pointer; display:inline-flex; align-items:center; gap:5px; box-shadow:inset 0 1px 0 rgba(255,255,255,.035); }
.finding-toggle::before { content:'▸'; color:var(--primary); font-size:10px; line-height:1; transform:translateY(-.5px); transition:transform .15s ease; }
.finding-toggle:hover { border-color:rgba(86,199,183,.42); color:#edfdfa; background:rgba(86,199,183,.10); }
.finding-toggle[aria-expanded="true"] { border-color:rgba(86,199,183,.52); color:#effffb; background:rgba(86,199,183,.16); }
.finding-toggle[aria-expanded="true"]::before { transform:rotate(90deg); }
.finding-detail { width:100%; border-collapse:collapse; table-layout:fixed; border:1px solid var(--line); background:#151d22; }
.finding-detail th, .finding-detail td { padding:6px 8px; border-bottom:1px solid #28353d; vertical-align:top; text-align:left; }
.finding-detail th { color:var(--muted); font-size:9px; text-transform:uppercase; letter-spacing:.06em; background:#202930; }
.finding-detail tr:last-child td { border-bottom:0; }
.finding-detail code { max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:inline-block; vertical-align:bottom; }
.finding-message { color:var(--ink-2); line-height:1.25; }
.pill { display:inline-flex; align-items:center; justify-content:center; min-width:62px; height:22px; padding:0 8px; border-radius:999px; font-size:10px; font-weight:900; letter-spacing:.06em; color:var(--c); background:color-mix(in srgb, var(--c) 14%, #1b2329); border:1px solid color-mix(in srgb, var(--c) 32%, #1b2329); box-shadow:none; }
.finding-cells { display:flex; gap:4px; flex-wrap:wrap; align-items:center; }
.sev-chip { display:inline-flex; min-width:24px; height:20px; align-items:center; justify-content:center; padding:0 6px; border-radius:5px; color:#081014; font-family:var(--mono); font-size:10px; font-weight:900; }
.sev { display:inline-flex; min-width:62px; height:22px; align-items:center; justify-content:center; border-radius:5px; color:#081014; font-size:10px; font-weight:900; letter-spacing:.05em; }
.plain-count { color:var(--ink-2); font-family:var(--mono); }
.risk-rail { display:block; padding:12px; }
.severity-stack { display:grid; gap:6px; align-content:start; }
.severity-mini { margin-top:9px; padding-top:8px; border-top:1px solid var(--line); display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; }
.severity-mini .score-label { color:var(--ink-2); font-size:11px; font-weight:950; text-transform:uppercase; letter-spacing:.07em; }
.severity-mini .score-arrow { width:15px; height:15px; margin:0 6px; color:var(--primary); vertical-align:-2px; }
.severity-mini b { color:var(--warn); font-size:18px; line-height:1; font-variant-numeric:tabular-nums; margin-left:6px; }
.severity-mini code { justify-self:end; }
.sev-row { display:grid; grid-template-columns: 72px 1fr 42px; gap:8px; align-items:center; }
.sev-row label { color:var(--ink-3); font-size:10px; font-weight:900; text-transform:uppercase; letter-spacing:.06em; }
.track { height:18px; background:#2a343b; border-radius:6px; overflow:hidden; border:1px solid rgba(255,255,255,.04); }
.fill { height:100%; width:var(--w); background:var(--bar); box-shadow:0 0 10px color-mix(in srgb, var(--bar) 14%, transparent); }
.sev-row strong { font-family:var(--mono); font-size:12px; text-align:right; color:var(--ink-2); }
.two-col { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.below-matrix { margin-top:14px; }
.dense-list { padding:8px 12px 12px; display:grid; gap:7px; }
.kv { display:grid; grid-template-columns: minmax(0,1fr) auto; gap:12px; align-items:center; min-height:28px; border-bottom:1px solid #2d3a42; }
.kv:last-child { border-bottom:0; }
.kv code { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.kv strong { font-family:var(--mono); font-size:12px; color:var(--ink-2); }
.callout { margin:0; padding:10px 12px; border-bottom:1px solid var(--line); display:flex; gap:9px; align-items:flex-start; color:var(--ink-2); background:#2c1f22; }
.callout strong { color:var(--ink); }
.callout svg { width:16px; height:16px; flex:0 0 16px; color:var(--fail); }
.evidence-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(280px,1fr)); gap:10px; padding:12px; }
.evidence-item { width:100%; border:1px solid var(--line); border-radius:var(--radius); padding:10px; background:#202930; color:inherit; display:grid; gap:7px; text-align:left; cursor:pointer; appearance:none; }
.evidence-item:hover { border-color:#5a7079; background:#243039; }
.evidence-item.is-selected { border-color:var(--primary); box-shadow:0 0 0 1px rgba(86,199,183,.18), inset 3px 0 0 var(--primary); background:#213038; }
.evidence-item:focus-visible { outline:2px solid var(--primary); outline-offset:2px; }
.evidence-item .file { font-weight:800; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.evidence-item .meta { display:flex; justify-content:space-between; gap:10px; color:var(--ink-3); font-size:11px; font-family:var(--mono); }
.evidence-preview { margin:0 12px 12px; border:1px solid var(--line); border-radius:var(--radius); overflow:hidden; background:#11181d; }
.evidence-preview-bar { min-height:38px; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:8px 10px; border-bottom:1px solid var(--line); background:linear-gradient(180deg,#202a31,#182126); }
.evidence-preview-title { min-width:0; display:flex; align-items:center; gap:8px; color:var(--ink-2); font-weight:800; }
.evidence-preview-title code { max-width:70vw; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.evidence-preview-meta { color:var(--ink-3); font-family:var(--mono); font-size:11px; white-space:nowrap; }
.evidence-code { max-height:560px; overflow:auto; margin:0; padding:0; font-family:var(--mono); font-size:11px; line-height:1.5; background:#10171b; }
.evidence-line { display:grid; grid-template-columns:58px minmax(0,1fr); min-height:20px; }
.evidence-line:hover { background:#172228; }
.evidence-ln { position:sticky; left:0; z-index:1; padding:0 10px; color:#687a82; text-align:right; user-select:none; background:#121b20; border-right:1px solid #26333b; font-variant-numeric:tabular-nums; }
.evidence-text { padding:0 12px; color:#d6e5df; white-space:pre; }
.evidence-truncated { padding:8px 12px; color:var(--warn); border-top:1px solid var(--line); background:#221f18; font-size:11px; }
.evidence-preview-empty { padding:18px; color:var(--muted); text-align:center; }
.assurance-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(150px,1fr)); gap:10px; padding:12px; }
.assurance-cell { border:1px solid var(--line); border-radius:var(--radius); background:#202930; padding:10px; }
.assurance-cell b { display:block; color:var(--ink); font-size:22px; line-height:1; font-variant-numeric:tabular-nums; }
.assurance-cell span { display:block; margin-top:6px; color:var(--ink-3); font-size:10px; text-transform:uppercase; letter-spacing:.07em; }
.manual-checklist { border-top:1px solid var(--line); }
.manual-tools { min-height:42px; padding:9px 12px; display:flex; align-items:center; justify-content:space-between; gap:12px; border-bottom:1px solid var(--line); background:#1b252b; }
.manual-tools strong { color:var(--ink-2); font-size:12px; text-transform:uppercase; letter-spacing:.06em; }
.manual-actions { display:flex; gap:7px; flex-wrap:wrap; }
.mini-btn { height:28px; padding:0 9px; border:1px solid rgba(86,199,183,.28); border-radius:6px; background:rgba(86,199,183,.08); color:#d9fff8; font-size:11px; font-weight:800; cursor:pointer; }
.mini-btn:hover { background:rgba(86,199,183,.15); border-color:rgba(86,199,183,.48); }
.manual-table { width:100%; border-collapse:collapse; table-layout:fixed; }
.manual-table th, .manual-table td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
.manual-table th { color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.06em; background:#202930; }
.manual-table tr:last-child td { border-bottom:0; }
.manual-table .check-col { width:48px; text-align:center; }
.manual-table .item-col { width:230px; font-weight:850; color:var(--ink); }
.manual-table input[type="checkbox"] { width:16px; height:16px; accent-color:var(--primary); cursor:pointer; }
.manual-desc { color:var(--ink-2); line-height:1.35; }
.manual-evidence { margin-top:4px; color:var(--ink-3); font-size:11px; line-height:1.35; }
.manual-body { padding:12px 14px; max-height:540px; overflow:auto; }
.manual-body h2:first-child { margin-top:0; }
.manual-body h2 { font-size:16px; margin:18px 0 8px; color:var(--ink); }
.manual-body h3 { font-size:13px; margin:16px 0 6px; color:var(--ink); }
.manual-body h4 { font-size:12px; margin:12px 0 6px; color:var(--ink-2); }
.manual-body p, .manual-body li { color:var(--ink-2); }
.manual-body ul, .manual-body ol { padding-left:20px; }
.manual-body code { white-space:normal; }
.prompt-shell { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); overflow:hidden; box-shadow:var(--shadow); }
.prompt-bar { min-height:52px; padding:12px 14px; display:flex; align-items:center; justify-content:space-between; gap:14px; border-bottom:1px solid var(--line); background:linear-gradient(180deg,#26313a,#1d252b); color:#fff; }
.prompt-bar h2 { margin:0; font-size:14px; }
.prompt-bar .meta { color:rgba(238,247,243,.62); font-size:11px; margin-top:2px; }
.copy-btn { height:34px; border:1px solid rgba(86,199,183,.30); background:rgba(86,199,183,.10); color:#dffff8; border-radius:7px; padding:0 12px; display:flex; gap:7px; align-items:center; cursor:pointer; }
.copy-btn:hover { background:rgba(86,199,183,.18); }
.copy-btn svg { width:15px; height:15px; }
.copy-btn.copied { background:var(--pass); color:#06130c; }
.prompt-body { padding:16px 18px; max-height:760px; overflow:auto; }
.prompt-body h2:first-child { margin-top:0; }
.prompt-body h2 { font-size:18px; margin:24px 0 10px; color:var(--ink); }
.prompt-body h3 { font-size:14px; margin:18px 0 8px; color:var(--ink); }
.prompt-body h4 { font-size:12px; margin:14px 0 6px; color:var(--ink-2); }
.prompt-body p, .prompt-body li { color:var(--ink-2); }
.prompt-body ul, .prompt-body ol { padding-left:22px; }
.prompt-body pre.md-code { background:#12191d; color:#dcfff8; border:1px solid #34484f; padding:12px; border-radius:7px; overflow:auto; font-family:var(--mono); font-size:12px; }
.prompt-body blockquote { border-left:3px solid var(--primary); margin:12px 0; padding:8px 12px; background:#1b3438; color:var(--ink-2); }
.prompt-body .md-table-wrap { overflow:auto; }
.prompt-body table.md-table { width:100%; border-collapse:collapse; font-size:12px; }
.prompt-body table.md-table th, .prompt-body table.md-table td { border:1px solid var(--line); padding:6px 8px; text-align:left; }
.prompt-body table.md-table th { background:#202930; color:var(--ink-2); }
.empty-state { padding:16px; color:var(--muted); text-align:center; }
@media (max-width:1100px) { .topbar, .command-strip, .overview-grid { grid-template-columns:1fr; } .nav { display:grid; grid-template-columns:1fr 1fr; justify-self:stretch; } .scan-meta table { table-layout:auto; } }
@media (max-width:760px) { .shell { padding:12px 12px 28px; } .topbar { grid-template-columns:1fr; } .scan-meta table, .scan-meta tbody, .scan-meta tr, .scan-meta th, .scan-meta td { display:block; width:100%; } .scan-meta th, .scan-meta td { border-right:0; } .scan-meta td { border-bottom:1px solid var(--line); } .scan-meta tr:last-child td:last-child { border-bottom:0; } .metric-grid { grid-template-columns:repeat(3,1fr); } .two-col { grid-template-columns:1fr; } .matrix { min-width:840px; } .card { overflow:auto; } .nav { grid-template-columns:1fr; } .tab-btn { height:38px; } }

/* (Phase 2 Compliance Matrix CSS removed — pivot to FR-driven model) */

/* FR Catalog tab (Phase 1.5) */
.fr-status-badge { display:inline-flex; align-items:center; min-width:62px; height:20px; padding:0 8px; border-radius:5px; color:#081014; font-size:10px; font-weight:900; letter-spacing:.05em; text-transform:uppercase; }
.fr-row { cursor:pointer; transition:background .1s; }
.fr-row:hover { background:#243039; }
.fr-row:focus { outline:2px solid var(--primary); outline-offset:-2px; }
.fr-row-child td:first-child { padding-left:24px; }
.fr-link-count { display:inline-block; min-width:32px; padding:2px 6px; margin-right:4px; border-radius:4px; background:rgba(86,199,183,.08); color:var(--ink-3); font-family:var(--mono); font-size:10px; font-weight:700; text-align:center; }
.fr-detail { padding:12px 14px; background:#172025; border:1px solid var(--line); border-radius:var(--radius); }
.fr-detail-desc { color:var(--ink-2); margin-bottom:10px; line-height:1.5; }
.fr-detail-section { margin-top:8px; font-size:11px; color:var(--ink-3); }
.fr-detail-section strong { color:var(--ink-2); text-transform:uppercase; letter-spacing:.05em; font-size:10px; }
.fr-detail-section ul { padding-left:18px; margin:4px 0 0; }
.fr-detail-section li { margin:2px 0; }
.fr-filter-bar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; padding:10px 12px; }
.fr-search-input, .fr-select { background:var(--surface-2); border:1px solid var(--line); color:var(--ink-2); border-radius:6px; padding:6px 10px; font-size:12px; min-width:140px; }
.fr-search-input { flex:1; min-width:200px; }
.fr-search-input:focus, .fr-select:focus { outline:none; border-color:var(--primary); }
.fr-row.hidden-by-filter, .fr-detail-row.hidden-by-filter, .fr-category-header.hidden-by-filter { display:none; }

/* Framework tabs (Phase 1.6) */
.fw-scope-header { padding:10px 12px; color:var(--ink-3); font-size:12px; border-bottom:1px solid var(--line); }
.fw-scope-header code { background:#183236; color:#baf4ea; padding:2px 6px; border-radius:4px; font-size:11px; }
.fw-state-badge { display:inline-flex; align-items:center; justify-content:center; min-width:78px; height:22px; padding:0 10px; border-radius:5px; font-size:10px; font-weight:900; letter-spacing:.05em; text-transform:uppercase; }
.fw-row { cursor:pointer; transition:background .1s; }
.fw-row:hover { background:#243039; }
.fw-row:focus { outline:2px solid var(--primary); outline-offset:-2px; }
.fw-row-filtered { opacity:.4; }
.fw-fr-link { display:inline-block; margin-right:4px; padding:1px 5px; border-radius:3px; background:rgba(86,199,183,.08); font-size:10px; }
.fw-detail { padding:12px 14px; background:#172025; border:1px solid var(--line); border-radius:var(--radius); }
.fw-row-desc { color:var(--ink-2); margin-bottom:8px; line-height:1.5; }
.fw-row-detail { font-size:11px; color:var(--ink-3); margin-top:6px; }
.fw-row-detail strong { color:var(--ink-2); }
.fw-culprit-list { list-style:none; padding-left:0; margin:6px 0 0; display:grid; gap:4px; }
.fw-culprit-item { padding:5px 8px; background:rgba(255,77,109,.07); border-left:3px solid var(--fail); border-radius:4px; font-size:11px; }
.fw-filter-bar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; padding:10px 12px; }
.fw-search-input, .fw-select { background:var(--surface-2); border:1px solid var(--line); color:var(--ink-2); border-radius:6px; padding:6px 10px; font-size:12px; min-width:140px; }
.fw-search-input { flex:1; min-width:200px; }
.fw-search-input:focus, .fw-select:focus { outline:none; border-color:var(--primary); }
.fw-toggle { display:inline-flex; align-items:center; gap:4px; color:var(--ink-3); font-size:11px; cursor:pointer; }
.fw-row.hidden-by-filter, .fw-detail-row.hidden-by-filter, .fw-group-header.hidden-by-filter { display:none !important; }

/* Findings ASVS impact button (Phase 2) */
.asvs-impact-btn { display:inline-block; margin-top:4px; padding:2px 8px; border:1px solid rgba(255,77,109,.4); border-radius:4px; background:rgba(255,77,109,.1); color:#ff8a9b; font-size:10px; font-weight:700; cursor:pointer; text-transform:uppercase; letter-spacing:.03em; }
.asvs-impact-btn:hover { background:rgba(255,77,109,.2); border-color:rgba(255,77,109,.6); }

/* Coverage Heatmap (Phase 3) */
.heat-body { padding:12px; }
.heat-framework { margin-bottom:16px; }
.heat-framework h3 { font-size:12px; text-transform:uppercase; letter-spacing:.07em; color:var(--ink-2); margin:0 0 8px; }
.heat-grid { display:flex; flex-wrap:wrap; gap:4px; }
.heat-cell { display:inline-flex; flex-direction:column; align-items:center; min-width:54px; padding:6px 8px; border-radius:6px; background:rgba(86,199,183,.06); border:1px solid var(--line); cursor:default; }
.heat-label { font-size:11px; font-weight:800; color:var(--ink); }
.heat-pct { font-size:16px; font-weight:900; }
.heat-count { font-size:9px; color:var(--ink-3); }
"""


# ===========================================================================
# Tab renderers
# ===========================================================================

def finding_total(value) -> int:
    if isinstance(value, dict):
        return sum(v for v in value.values() if isinstance(v, int))
    if isinstance(value, int):
        return value
    return 0


def aggregate_severity_strict(findings: dict) -> dict:
    out = {s: 0 for s in SEVERITY_ORDER}
    for value in findings.values():
        if isinstance(value, dict):
            for sev in SEVERITY_ORDER:
                out[sev] += value.get(sev, 0)
    return out


def actionable_finding_total(findings: dict) -> int:
    total = 0
    for name, value in findings.items():
        if name == 'syft':
            continue
        total += finding_total(value)
    return total


def finding_markup(value) -> str:
    if isinstance(value, dict):
        chips = []
        for sev in SEVERITY_ORDER:
            n = value.get(sev, 0)
            if n:
                chips.append(f'<span class="sev-chip" title="{sev}" style="background:{SEVERITY_COLORS.get(sev, C["unknown"])}">{sev[0]} {n}</span>')
        return f'<div class="finding-cells">{"".join(chips) if chips else "<span class=\"plain-count\">clean</span>"}</div>'
    if isinstance(value, int):
        return f'<span class="plain-count">{value:,}</span>' if value else '<span class="plain-count">clean</span>'
    return '<span class="plain-count">-</span>'


def scanner_finding_value(name: str, findings: dict):
    return findings.get(name) if name in findings else findings.get(name.replace('-', '_'))


def scanner_output_link(name: str) -> str:
    info = SCANNERS.get(name, {})
    return info.get('output', '')


def output_family(file_name: str) -> tuple[str, str]:
    if file_name.endswith('.cyclonedx.json'):
        return file_name[:-len('.cyclonedx.json')], '.cyclonedx.json'
    suffixes = ''.join(Path(file_name).suffixes)
    return (file_name[:-len(suffixes)], suffixes) if suffixes else (file_name, '')


def evidence_markup(evidence: dict, name: str) -> str:
    base = scanner_output_link(name)
    if not base:
        return '<code>-</code>'
    base_path = Path(base)
    prefix, suffix = output_family(base_path.name)
    files = []
    for item in evidence.get('evidence_files', []) or []:
        file_path = str(item.get('file', ''))
        path = Path(file_path)
        if path.parent.as_posix() != base_path.parent.as_posix():
            continue
        fname = path.name
        if fname == base_path.name or (fname.startswith(prefix + '-') and fname.endswith(suffix)):
            files.append(file_path)
    files = sorted(set(files))
    if not files:
        files = [base]
    if len(files) == 1:
        return f'<code>{html.escape(files[0])}</code>'
    title = html.escape('\n'.join(files))
    return f'<code title="{title}">{len(files)} files</code>'


def compact_list(value) -> str:
    if isinstance(value, list):
        clean = [str(v) for v in value if v]
        if not clean:
            return ''
        if len(clean) == 1:
            return clean[0]
        return f'{len(clean)} targets'
    return str(value or '')


def git_branch_name(target_dir: str) -> str:
    if not target_dir or target_dir == '-':
        return ''
    try:
        result = subprocess.run(
            ['git', '-C', target_dir, 'branch', '--show-current'],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        branch = result.stdout.strip()
        if branch:
            return branch
        result = subprocess.run(
            ['git', '-C', target_dir, 'rev-parse', '--short', 'HEAD'],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        short = result.stdout.strip()
        return f'detached@{short}' if short else ''
    except Exception:
        return ''


def git_repo_name(target_dir: str) -> str:
    if not target_dir or target_dir == '-':
        return ''
    try:
        result = subprocess.run(
            ['git', '-C', target_dir, 'remote', 'get-url', 'origin'],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        remote = result.stdout.strip().rstrip('/')
        if remote:
            name = remote.rsplit('/', 1)[-1]
            if ':' in name:
                name = name.rsplit(':', 1)[-1]
            return re.sub(r'\.git$', '', name)
    except Exception:
        pass
    try:
        result = subprocess.run(
            ['git', '-C', target_dir, 'rev-parse', '--show-toplevel'],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        top = result.stdout.strip()
        if top:
            return Path(top).name
    except Exception:
        pass
    return Path(target_dir).name


def fmt_bytes(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return '-'
    units = ['B', 'KB', 'MB', 'GB']
    size = float(n)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f'{size:.1f} {u}' if u != 'B' else f'{int(size)} B'
        size /= 1024


def read_evidence_preview(report_dir: Path, rel_file: str) -> dict:
    rel = str(rel_file or '')
    safe_rel = rel.lstrip('/').replace('\\', '/')
    path = (report_dir / safe_rel).resolve()
    root = report_dir.resolve()
    if root not in path.parents and path != root:
        return {'file': rel, 'content': 'Preview blocked: file is outside the report directory.', 'truncated': False, 'error': True}
    if not path.exists() or not path.is_file():
        return {'file': rel, 'content': 'Preview unavailable: file was not found in this report.', 'truncated': False, 'error': True}

    suffixes = ''.join(path.suffixes).lower()
    is_json = suffixes.endswith('.json') or suffixes.endswith('.sarif') or suffixes.endswith('.cyclonedx.json')
    is_jsonl = suffixes.endswith('.jsonl')
    truncated = False

    if is_json or is_jsonl:
        # Parse complete structured evidence first. Truncating before json.loads()
        # makes large but valid scanner outputs render as one unreadable line.
        raw = path.read_bytes()
    else:
        raw = path.read_bytes()[:PREVIEW_MAX_BYTES + 1]
        truncated = len(raw) > PREVIEW_MAX_BYTES
        if truncated:
            raw = raw[:PREVIEW_MAX_BYTES]

    text = raw.decode('utf-8', errors='replace')
    if is_json:
        try:
            text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except Exception:
            pass
    elif is_jsonl:
        pretty_lines = []
        changed = False
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                pretty_lines.append('')
                continue
            try:
                pretty_lines.append(json.dumps(json.loads(stripped), indent=2, ensure_ascii=False))
                changed = True
            except Exception:
                pretty_lines.append(line)
        if changed:
            text = '\n'.join(pretty_lines)
    lines = text.splitlines()
    if len(lines) > PREVIEW_MAX_LINES:
        text = '\n'.join(lines[:PREVIEW_MAX_LINES])
        truncated = True
    return {'file': rel, 'content': text, 'truncated': truncated, 'error': False}


def evidence_preview_script(previews: list[dict]) -> str:
    payload = json.dumps(previews, ensure_ascii=False).replace('</', '<\\/')
    return f'<script type="application/json" id="evidence-preview-data">{payload}</script>'


def scan_surface_groups() -> list[tuple[str, str, list[str]]]:
    return [
        ('Code', 'SAST, secrets, filesystem and config analysis', ['semgrep', 'gitleaks', 'trivy-fs', 'trivy-config']),
        ('Supply Chain', 'SBOM generation and vulnerability matching', ['syft', 'grype', 'osv-scanner']),
        ('Container Image', 'built image SBOM and vulnerability checks', ['trivy-image', 'syft-image', 'grype-image']),
        ('Runtime Surface', 'web app, headers and TLS checks', ['zap-baseline', 'security-headers', 'testssl']),
        ('Uploads & Malware', 'uploaded content scanning', ['clamav']),
    ]


