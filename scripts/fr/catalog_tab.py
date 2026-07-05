#!/usr/bin/env python3
"""FR Catalog tab renderer."""
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

# FR Catalog tab (Phase 1.5 — minimal list view)
# ===========================================================================

def render_fr_catalog(fr_catalog_path: str) -> str:
    """Render the FR Catalog tab as HTML."""
    import importlib.util
    loader_path = Path(__file__).resolve().parent.parent / "load_fr_catalog.py"
    spec = importlib.util.spec_from_file_location("load_fr_catalog", loader_path)
    if spec is None or spec.loader is None:
        return _fr_catalog_error("Could not load FR catalog loader module.")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)  # type: ignore[union-attr]

    try:
        catalog = loader.load_fr_catalog(Path(fr_catalog_path))
    except loader.FrCatalogError as exc:
        return _fr_catalog_error(str(exc))

    requirements = catalog.requirements
    if not requirements:
        return (
            '<section class="card"><div class="empty-state">'
            'No functional requirements defined. Add an FR to fr-catalog.json and rescan.'
            '</div></section>'
        )

    # Index by parent for hierarchy rendering
    by_parent: dict[str | None, list[dict]] = {}
    for req in requirements:
        parent = req.get("parent")
        by_parent.setdefault(parent, []).append(req)

    valid_ids = {r["id"] for r in requirements}
    top_level = [r for r in requirements if not r.get("parent") or r.get("parent") not in valid_ids]

    from collections import defaultdict
    by_category: dict[str, list[dict]] = defaultdict(list)
    for req in top_level:
        cat = req.get("category", "uncategorized")
        by_category[cat].append(req)

    total = len(requirements)
    with_code = sum(1 for r in requirements if r.get("implemented_by"))
    with_tests = sum(1 for r in requirements if r.get("verified_by"))
    with_compliance = sum(1 for r in requirements if r.get("satisfies"))
    tiles = (
        f'<div class="metric"><b>{total}</b><span>Total FRs</span></div>'
        f'<div class="metric"><b>{with_code}</b><span>With code refs</span></div>'
        f'<div class="metric"><b>{with_tests}</b><span>With test refs</span></div>'
        f'<div class="metric"><b>{with_compliance}</b><span>With compliance links</span></div>'
    )

    filter_bar = """
    <div class="card-head fr-filter-bar">
      <input type="search" id="fr-search" placeholder="Search FR ID or title..." class="fr-search-input">
      <select id="fr-category-filter" class="fr-select">
        <option value="">All categories</option>
      </select>
      <select id="fr-status-filter" class="fr-select">
        <option value="">All statuses</option>
        <option value="active" selected>Active</option>
        <option value="draft">Draft</option>
        <option value="deprecated">Deprecated</option>
        <option value="proposed">Proposed</option>
      </select>
    </div>
    """

    rows_html: list[str] = []
    for category in sorted(by_category.keys()):
        cat_reqs = by_category[category]
        rows_html.append(
            f'<tr class="category-row fr-category-header" data-category="{html.escape(category)}">'
            f'<td colspan="5">{html.escape(category)} '
            f'<span class="category-meta">· {len(cat_reqs)} top-level FRs</span></td></tr>'
        )
        for req in cat_reqs:
            rows_html.extend(_render_fr_row(req, by_parent, depth=0))

    warning_banner = ""
    warn_items = [w for w in catalog.warnings if w.severity == "warn"]
    if warn_items:
        items = "".join(
            f'<li>[{w.severity}] {html.escape(w.code)}: {html.escape(w.message)}</li>'
            for w in warn_items
        )
        warning_banner = (
            f'<div class="callout"><strong>{len(warn_items)} validation warning(s):</strong>'
            f'<ul>{items}</ul></div>'
        )

    body = (
        f'{warning_banner}'
        f'<section class="card fr-card">'
        f'<div class="metric-grid" style="grid-template-columns:repeat(4,minmax(120px,1fr));margin-bottom:12px">{tiles}</div>'
        f'{filter_bar}'
        f'<table class="matrix fr-table"><thead><tr>'
        f'<th>ID</th><th>Title</th><th>Status</th><th>Owner</th><th>Links</th>'
        f'</tr></thead><tbody>{"".join(rows_html)}</tbody></table>'
        f'</section>'
    )
    return body


def _render_fr_row(req: dict, by_parent: dict, depth: int) -> list[str]:
    """Render one FR row + its child rows (recursive)."""
    indent = "&nbsp;" * (depth * 4)
    rid = html.escape(req.get("id", ""))
    title = html.escape(req.get("title", ""))
    status = html.escape(req.get("status", ""))
    owner = html.escape(req.get("owner", "") or "—")
    impl_count = len(req.get("implemented_by") or [])
    verified_count = len(req.get("verified_by") or [])
    satisfies_count = len(req.get("satisfies") or [])

    status_color = {"active": "#35d07f", "draft": "#ffd166",
                    "deprecated": "#718096", "proposed": "#56c7b7"}.get(status, "#718096")
    status_badge = (f'<span class="fr-status-badge" style="background:{status_color}">'
                    f'{status}</span>')

    links = (
        f'<span class="fr-link-count" title="Code refs">{impl_count} F</span> '
        f'<span class="fr-link-count" title="Test refs">{verified_count} T</span> '
        f'<span class="fr-link-count" title="Compliance rows">{satisfies_count} C</span>'
    )

    detail_parts: list[str] = []
    if req.get("description"):
        detail_parts.append(f'<div class="fr-detail-desc">{html.escape(req["description"])}</div>')
    if req.get("implemented_by"):
        items = []
        for r in req["implemented_by"]:
            path = html.escape(r.get("path", ""))
            label = r.get("label")
            label_str = f" &mdash; {html.escape(label)}" if label else ""
            items.append(f'<li><code>{path}</code>{label_str}</li>')
        detail_parts.append(f'<div class="fr-detail-section"><strong>Code:</strong><ul>{"".join(items)}</ul></div>')
    if req.get("verified_by"):
        items = []
        for r in req["verified_by"]:
            rtype = html.escape(r.get("type", ""))
            rref = html.escape(r.get("ref", ""))
            items.append(f'<li><code>{rtype}</code>: <code>{rref}</code></li>')
        detail_parts.append(f'<div class="fr-detail-section"><strong>Verified by:</strong><ul>{"".join(items)}</ul></div>')
    if req.get("satisfies"):
        items = []
        for s in req["satisfies"]:
            fw = html.escape(s.get("framework", ""))
            row = html.escape(s.get("row", ""))
            reason = s.get("reason")
            reason_str = f" <em>({html.escape(reason)})</em>" if s.get("status") == "na" and reason else ""
            items.append(f'<li>{fw} &rarr; <code>{row}</code>{reason_str}</li>')
        detail_parts.append(f'<div class="fr-detail-section"><strong>Satisfies:</strong><ul>{"".join(items)}</ul></div>')
    if req.get("evidence"):
        items = "".join(
            f'<li>{html.escape(e.get("type", ""))}: <code>{html.escape(e.get("ref", ""))}</code></li>'
            for e in req["evidence"]
        )
        detail_parts.append(f'<div class="fr-detail-section"><strong>Evidence:</strong><ul>{items}</ul></div>')

    detail_html = ""
    if detail_parts:
        detail_html = f'<div class="fr-detail">{"".join(detail_parts)}</div>'

    row_class = "fr-row" + (" fr-row-child" if depth > 0 else "")
    rows = [
        f'<tr class="{row_class}" data-fr-id="{rid}" data-status="{status}" '
        f'data-category="{html.escape(req.get("category", ""))}" tabindex="0" role="button" aria-expanded="false">'
        f'<td><code>{rid}</code></td>'
        f'<td>{indent}{title}</td>'
        f'<td>{status_badge}</td>'
        f'<td>{owner}</td>'
        f'<td>{links}</td>'
        f'</tr>'
    ]
    if detail_html:
        rows.append(
            f'<tr class="fr-detail-row" data-fr-id="{rid}" hidden>'
            f'<td colspan="5">{detail_html}</td></tr>'
        )
    for child in by_parent.get(req["id"], []):
        rows.extend(_render_fr_row(child, by_parent, depth + 1))
    return rows


def _fr_catalog_error(message: str) -> str:
    return (
        '<section class="card"><div class="callout"><strong>FR catalog error:</strong><br>'
        f'{html.escape(message)}<br><br>'
        'Fix the catalog and rescan.</div></section>'
    )


# ===========================================================================

