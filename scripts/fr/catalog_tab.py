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

def render_fr_catalog(
    fr_catalog_path: str,
    assurance_status: dict | None = None,
    report_dir: str | Path | None = None,
) -> str:
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

    frs = getattr(catalog, "frs", []) or []
    tbts = getattr(catalog, "tbts", []) or []
    if not frs:
        return (
            '<section class="card"><div class="empty-state">'
            'No functional requirements defined. Add an FR to fr-catalog.json and rescan.'
            '</div></section>'
        )

    # Index by parent for hierarchy rendering
    by_parent: dict[str | None, list[dict]] = {}
    for req in frs:
        parent = req.get("parent")
        by_parent.setdefault(parent, []).append(req)

    valid_ids = {r["id"] for r in frs}
    top_level = [r for r in frs if not r.get("parent") or r.get("parent") not in valid_ids]
    tbts_by_fr: dict[str, list[dict]] = {fr_id: [] for fr_id in valid_ids}
    for tbt in tbts:
        for fr_id in tbt.get("proves") or []:
            tbts_by_fr.setdefault(fr_id, []).append(tbt)
    artifact_dir = Path(report_dir) if report_dir is not None else Path(fr_catalog_path).parent
    test_pack_by_tbt = _load_assurance_pack_by_tbt(artifact_dir)
    assurance_status = assurance_status or {}
    fr_status_by_id = {
        item.get("id"): item
        for item in assurance_status.get("frs", []) or []
        if item.get("id")
    }
    tbt_status_by_id = {
        item.get("id"): item
        for item in assurance_status.get("tbts", []) or []
        if item.get("id")
    }
    scanner_blockers_by_fr = _scanner_blockers_by_fr(assurance_status)
    scanner_blockers_by_row = _scanner_blockers_by_row(assurance_status)

    from collections import defaultdict
    by_category: dict[str, list[dict]] = defaultdict(list)
    for req in top_level:
        cat = req.get("category", "uncategorized")
        by_category[cat].append(req)

    catalog_name = Path(fr_catalog_path).name
    intro = (
        '<div class="page-intro">'
        '<div>'
        '<h2>Project Functional Requirements</h2>'
        '<ul>'
        '<li>Declares the assurance scope for this scan</li>'
        '<li>Maps project FRs to TBTs, evidence and compliance rows</li>'
        '<li>Expands each FR to show provenance and gaps</li>'
        '</ul>'
        '</div>'
        f'<code>{html.escape(catalog_name)}</code>'
        '</div>'
    )

    filter_bar = """
    <div class="card-head fr-filter-bar">
      <input type="search" id="fr-search" placeholder="Search FR ID or title..." class="fr-search-input">
      <select id="fr-category-filter" class="fr-select">
        <option value="">All epics</option>
      </select>
      <select id="fr-status-filter" class="fr-select">
        <option value="">All statuses</option>
        <option value="in_scope" selected>In scope</option>
        <option value="draft">Draft</option>
        <option value="deferred">Deferred</option>
        <option value="not_applicable">Not applicable</option>
        <option value="retired">Retired</option>
      </select>
    </div>
    """

    rows_html: list[str] = []
    for category in sorted(by_category.keys()):
        cat_reqs = by_category[category]
        rows_html.append(
            f'<tr class="category-row fr-category-header" data-category="{html.escape(category)}">'
            f'<td colspan="5">{html.escape(category)} '
            f'<span class="category-meta">· Epic · {len(cat_reqs)} FRs</span></td></tr>'
        )
        for req in cat_reqs:
            rows_html.extend(
                _render_fr_row(
                    req,
                    by_parent,
                    tbts_by_fr,
                    fr_status_by_id,
                    tbt_status_by_id,
                    scanner_blockers_by_fr,
                    scanner_blockers_by_row,
                    test_pack_by_tbt,
                    depth=0,
                )
            )

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
        f'{intro}'
        f'{filter_bar}'
        f'<table class="matrix fr-table"><thead><tr>'
        f'<th>ID</th><th>Status</th><th>Owner</th><th>Refs</th><th>Assurance</th>'
        f'</tr></thead><tbody>{"".join(rows_html)}</tbody></table>'
        f'</section>'
    )
    return body


def _render_fr_row(
    req: dict,
    by_parent: dict,
    tbts_by_fr: dict[str, list[dict]],
    fr_status_by_id: dict[str, dict],
    tbt_status_by_id: dict[str, dict],
    scanner_blockers_by_fr: dict[str, list[dict]],
    scanner_blockers_by_row: dict[str, list[dict]],
    test_pack_by_tbt: dict[str, dict],
    depth: int,
) -> list[str]:
    """Render one FR row + its child rows (recursive)."""
    indent = "&nbsp;" * (depth * 4)
    rid = html.escape(req.get("id", ""))
    title = html.escape(req.get("title", ""))
    status = html.escape(req.get("lifecycle_status", req.get("status", "")))
    assurance = fr_status_by_id.get(req.get("id", "")) or {}
    assurance_state = assurance.get("status", "unknown")
    assurance_label, assurance_title = _assurance_badge_copy(assurance_state)
    assurance_class = html.escape(str(assurance_state or "unknown"))
    owner_raw = str(req.get("owner") or "—")
    owner = html.escape(owner_raw)
    impl_count = len(req.get("implemented_by") or [])
    fr_tbts = tbts_by_fr.get(req.get("id", ""), [])
    verified_count = len(fr_tbts)
    tbt_compliance_rows = []
    seen_tbt_rows: set[tuple[str, str]] = set()
    for tbt in fr_tbts:
        for row in tbt.get("compliance") or []:
            key = (row.get("ruleset", ""), row.get("row", ""))
            if not key[0] or not key[1] or key in seen_tbt_rows:
                continue
            seen_tbt_rows.add(key)
            tbt_compliance_rows.append(row)
    satisfies_count = len(tbt_compliance_rows)

    status_label = {
        "in_scope": "in scope",
        "not_applicable": "not applicable",
    }.get(status, status)
    status_text = f'<span class="fr-status-text">{html.escape(status_label)}</span>'

    links = (
        f'<span class="fr-link-count" title="Code references declared in implemented_by">Code {impl_count}</span>'
        f'<span class="fr-link-count" title="Test Basis records proving this FR">TBT {verified_count}</span>'
        f'<span class="fr-link-count" title="Compliance or ruleset rows covered by this FR&apos;s TBTs">Rules {satisfies_count}</span>'
    )
    assurance_cell = '<span class="fr-assurance-text">—</span>'
    if assurance_state and assurance_state != "unknown":
        assurance_cell = (
            f'<span class="fr-assurance-text assurance-state-{assurance_class}" '
            f'title="{html.escape(assurance_title)}">{html.escape(assurance_label)}</span>'
        )

    detail_parts: list[str] = [
        _render_project_context_table(req, status_label, owner_raw),
        _render_framework_context_table(req),
        _render_code_references_table(req),
        _render_lineage_table(req, fr_tbts),
        _render_compliance_context_table(req, fr_tbts),
        _render_fr_chain_graph(
            req,
            fr_tbts,
            tbt_status_by_id,
            test_pack_by_tbt,
            scanner_blockers_by_row,
        ),
        _render_assurance_chain_table(
            req,
            fr_tbts,
            tbt_status_by_id,
            test_pack_by_tbt,
        ),
    ]
    if assurance.get("reasons"):
        detail_parts.append(_render_assurance_summary(assurance.get("reasons") or []))
    scanner_blockers = scanner_blockers_by_fr.get(req.get("id", "")) or []
    if scanner_blockers:
        detail_parts.append(_render_scanner_blockers(scanner_blockers))

    detail_html = ""
    if detail_parts:
        detail_html = f'<div class="fr-detail">{"".join(detail_parts)}</div>'

    row_class = "fr-row" + (" fr-row-child" if depth > 0 else "")
    rows = [
        f'<tr class="{row_class}" data-fr-id="{rid}" data-status="{status}" '
        f'data-category="{html.escape(req.get("category", ""))}" tabindex="0" role="button" aria-expanded="false">'
        f'<td><code>{rid}</code></td>'
        f'<td>{status_text}</td>'
        f'<td>{owner}</td>'
        f'<td>{links}</td>'
        f'<td>{assurance_cell}</td>'
        f'</tr>'
    ]
    if detail_html:
        rows.append(
            f'<tr class="fr-detail-row" data-fr-id="{rid}" hidden>'
            f'<td colspan="5">{detail_html}</td></tr>'
        )
    for child in by_parent.get(req["id"], []):
        rows.extend(_render_fr_row(child, by_parent, tbts_by_fr, fr_status_by_id, tbt_status_by_id, scanner_blockers_by_fr, scanner_blockers_by_row, test_pack_by_tbt, depth + 1))
    return rows


def _load_assurance_pack_by_tbt(report_dir: Path) -> dict[str, dict]:
    manifest = load_json(report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "manifest.json")
    if not isinstance(manifest, dict):
        return {}
    by_tbt: dict[str, dict] = {}
    for item in manifest.get("tests") or []:
        tbt_id = item.get("tbt")
        if not tbt_id:
            continue
        existing = by_tbt.get(tbt_id)
        if existing is None or _assurance_pack_item_priority(item) > _assurance_pack_item_priority(existing):
            by_tbt[tbt_id] = item
    return by_tbt


def _assurance_pack_item_priority(item: dict) -> int:
    status = str(item.get("status") or "")
    source = str(item.get("source") or "")
    safety = str(item.get("safety") or "")
    if status in {"executed", "observed"}:
        return 50
    if status == "ready_to_run" and safety == "non_destructive":
        return 40
    if source == "existing_asvs":
        return 35
    if source == "generated" or safety == "review_required":
        return 30
    if source == "wrapper_needed":
        return 20
    if source == "planned_tbt" or status == "planned":
        return 10
    return 0


def _render_project_context_table(req: dict, status_label: str, owner: str) -> str:
    code_refs = req.get("implemented_by") or []
    rows = [
        ("Lifecycle", status_label),
        ("Owner", owner),
        ("Code references", str(len(code_refs))),
    ]
    rows.append(("Description", str(req.get("description") or "No description supplied.")))
    return _render_info_table("Project context", rows, class_name="fr-project-context-table")


def _render_framework_context_table(req: dict) -> str:
    description = str(req.get("description") or "")
    gate = _gate_from_description(description)
    trace = _trace_from_description(description)
    source = _source_from_description(description)
    rows = []
    if gate:
        rows.append(("Gate", gate))
    if trace:
        rows.append(("Trace", trace))
    if source:
        rows.append(("Source document", source))
    if not rows:
        return _render_table_section(
            "Framework context",
            '<div class="fr-chain-empty">No framework gate, trace or source metadata is recorded for this FR.</div>',
        )
    return _render_info_table("Framework context", rows, class_name="fr-framework-context-table")


def _render_code_references_table(req: dict) -> str:
    code_refs = req.get("implemented_by") or []
    if not code_refs:
        return _render_table_section(
            "Code references",
            '<div class="fr-chain-empty">No code references are declared for this FR.</div>',
        )
    rows = []
    for ref in code_refs:
        path = html.escape(str(ref.get("path") or ""))
        label = html.escape(str(ref.get("label") or ""))
        rows.append(
            '<tr>'
            f'<td><code>{path}</code></td>'
            f'<td>{label or "<span class=\"fr-chain-muted\">No label</span>"}</td>'
            '</tr>'
        )
    return (
        '<section class="fr-table-section">'
        '<div class="fr-table-section-head"><strong>Code references</strong>'
        f'<span>{len(code_refs)} declared</span></div>'
        '<div class="fr-chain-table-wrap">'
        '<table class="fr-chain-table fr-code-table">'
        '<thead><tr><th>Path</th><th>Purpose</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></section>'
    )


def _render_lineage_table(req: dict, fr_tbts: list[dict]) -> str:
    fr_lineage = _lineage_summary(req.get("derived_from"))
    tbt_lineages = [
        (str(tbt.get("id") or ""), _lineage_summary(tbt.get("derived_from")))
        for tbt in fr_tbts
        if _lineage_summary(tbt.get("derived_from"))
    ]
    if not fr_lineage and not tbt_lineages:
        return _render_table_section(
            "Blueprint lineage",
            '<div class="fr-chain-empty">This FR is project specific; no blueprint lineage is recorded.</div>',
        )
    rows = []
    if fr_lineage:
        rows.append(
            '<tr>'
            '<td>FR</td>'
            f'<td><code>{html.escape(fr_lineage["item"])}</code></td>'
            f'<td>{html.escape(fr_lineage["version"]) or "<span class=\"fr-chain-muted\">Unversioned</span>"}</td>'
            f'<td>{html.escape(fr_lineage["review_status"]) or "<span class=\"fr-chain-muted\">No review state</span>"}</td>'
            '</tr>'
        )
    for tbt_id, lineage in tbt_lineages:
        rows.append(
            '<tr>'
            f'<td><code>{html.escape(tbt_id)}</code></td>'
            f'<td><code>{html.escape(lineage["item"])}</code></td>'
            f'<td>{html.escape(lineage["version"]) or "<span class=\"fr-chain-muted\">Unversioned</span>"}</td>'
            f'<td>{html.escape(lineage["review_status"]) or "<span class=\"fr-chain-muted\">No review state</span>"}</td>'
            '</tr>'
        )
    return (
        '<section class="fr-table-section fr-lineage-section">'
        '<div class="fr-table-section-head"><strong>Blueprint lineage</strong>'
        '<span>Reusable source artifacts</span></div>'
        '<div class="fr-chain-table-wrap">'
        '<table class="fr-chain-table fr-lineage-table">'
        '<thead><tr><th>Project item</th><th>Blueprint item</th><th>Version</th><th>Review</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></section>'
    )


def _render_compliance_context_table(req: dict, fr_tbts: list[dict]) -> str:
    rows = []
    for item in req.get("satisfies") or []:
        rows.append(_compliance_context_row("FR", req.get("id", ""), item))
    for tbt in fr_tbts:
        for item in tbt.get("compliance") or []:
            rows.append(_compliance_context_row("TBT", tbt.get("id", ""), item))
    if not rows:
        return _render_table_section(
            "Compliance mappings",
            '<div class="fr-chain-empty">No compliance rows are mapped to this FR or its TBTs.</div>',
        )
    return (
        '<section class="fr-table-section fr-compliance-section">'
        '<div class="fr-table-section-head"><strong>Compliance mappings</strong>'
        f'<span>{len(rows)} mapped row{"s" if len(rows) != 1 else ""}</span></div>'
        '<div class="fr-chain-table-wrap">'
        '<table class="fr-chain-table fr-compliance-table">'
        '<thead><tr><th>Scope</th><th>Item</th><th>Regime</th><th>Requirement</th><th>Relationship</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></section>'
    )


def _compliance_context_row(scope: str, item_id: Any, item: dict) -> str:
    ruleset = str(item.get("ruleset") or "")
    row = str(item.get("row") or item.get("row_id") or "")
    relationship = str(item.get("relationship") or item.get("status") or "satisfies")
    reason = str(item.get("reason") or "")
    relationship_text = relationship
    if relationship == "not_applicable" and reason:
        relationship_text = f"{relationship} - {reason}"
    return (
        '<tr>'
        f'<td>{html.escape(scope)}</td>'
        f'<td><code>{html.escape(str(item_id or ""))}</code></td>'
        f'<td>{html.escape(ruleset)}</td>'
        f'<td><code>{html.escape(row)}</code></td>'
        f'<td>{html.escape(relationship_text)}</td>'
        '</tr>'
    )


def _render_info_table(title: str, rows: list[tuple[str, str]], *, class_name: str = "") -> str:
    body = "".join(
        '<tr>'
        f'<th>{html.escape(label)}</th>'
        f'<td>{html.escape(str(value or ""))}</td>'
        '</tr>'
        for label, value in rows
    )
    table_class = f"fr-chain-table fr-info-table {html.escape(class_name)}".strip()
    return (
        '<section class="fr-table-section">'
        f'<div class="fr-table-section-head"><strong>{html.escape(title)}</strong></div>'
        '<div class="fr-chain-table-wrap">'
        f'<table class="{table_class}"><tbody>{body}</tbody></table></div></section>'
    )


def _render_table_section(title: str, body: str) -> str:
    return (
        '<section class="fr-table-section">'
        f'<div class="fr-table-section-head"><strong>{html.escape(title)}</strong></div>'
        f'{body}</section>'
    )


def _lineage_summary(derived_from: Any) -> dict[str, str] | None:
    if not isinstance(derived_from, dict):
        return None
    source_type = str(derived_from.get("source_type") or "")
    if not source_type.startswith("blueprint"):
        return None
    item = str(derived_from.get("source_item") or derived_from.get("source_id") or "")
    if not item:
        return None
    return {
        "item": item,
        "type": source_type,
        "version": str(derived_from.get("source_version") or ""),
        "path": str(derived_from.get("source_path") or ""),
        "hash": str(derived_from.get("source_hash") or ""),
        "review_status": str(derived_from.get("review_status") or ""),
    }


def _lineage_context_details(derived_from: Any) -> list[dict[str, str]]:
    lineage = _lineage_summary(derived_from)
    if not lineage:
        return [{"label": "Lineage", "value": "Project specific"}]
    details = [
        {"label": "Lineage", "value": "Blueprint derived"},
        {"label": "Blueprint", "value": lineage["item"]},
    ]
    if lineage["version"]:
        details.append({"label": "Blueprint version", "value": lineage["version"]})
    if lineage["review_status"]:
        details.append({"label": "Lineage review", "value": lineage["review_status"]})
    return details


def _render_assurance_summary(reasons: list) -> str:
    items = "".join(
        f'<li>{html.escape(str(reason))}</li>'
        for reason in reasons[:4]
    )
    if len(reasons) > 4:
        items += f'<li><em>and {len(reasons) - 4} more</em></li>'
    return (
        '<div class="fr-chain-note">'
        '<strong>Current assurance summary</strong>'
        f'<ul>{items}</ul>'
        '</div>'
    )


def _render_fr_chain_graph(
    req: dict,
    fr_tbts: list[dict],
    tbt_status_by_id: dict[str, dict],
    test_pack_by_tbt: dict[str, dict],
    scanner_blockers_by_row: dict[str, list[dict]],
) -> str:
    rid = str(req.get("id") or "FR")
    graph = _fr_local_graph_data(req, fr_tbts, tbt_status_by_id, test_pack_by_tbt, scanner_blockers_by_row)
    graph_json = json.dumps(graph, separators=(",", ":")).replace("<", "\\u003c")
    return (
        '<div class="fr-local-graph">'
        '<div class="fr-local-graph-head"><strong>Assurance chain</strong>'
        '<span>Click a node to inspect how this FR connects to TBTs, compliance rows, tests, scanner results and evidence.</span></div>'
        f'<div class="fr-local-d3" data-fr-local-graph="{html.escape(rid)}">'
        f'<script type="application/json" class="fr-local-graph-data">{graph_json}</script>'
        '<div class="fr-local-svg" aria-label="FR assurance chain graph"></div>'
        '<aside class="fr-local-context" aria-live="polite">'
        '<strong>Select a node</strong><span>Node details will appear here.</span>'
        '</aside>'
        '</div>'
        '</div>'
    )


def _fr_local_graph_data(
    req: dict,
    fr_tbts: list[dict],
    tbt_status_by_id: dict[str, dict],
    test_pack_by_tbt: dict[str, dict],
    scanner_blockers_by_row: dict[str, list[dict]],
) -> dict:
    rid = str(req.get("id") or "FR")
    nodes: list[dict] = [
        {
            "id": f"fr:{rid}",
            "type": "fr",
            "title": rid,
            "subtitle": str(req.get("title") or "Functional requirement"),
            "status": str(req.get("lifecycle_status") or req.get("status") or ""),
            "details": [
                {"label": "Title", "value": str(req.get("title") or "")},
                {"label": "Owner", "value": str(req.get("owner") or "")},
                {"label": "Description", "value": str(req.get("description") or "")},
            ] + _lineage_context_details(req.get("derived_from")),
        }
    ]
    edges: list[dict] = []
    row_nodes: set[str] = set()
    blueprint_nodes: set[str] = set()
    planning_nodes: set[str] = set()

    def add_lineage_node(owner_id: str, derived_from: Any) -> None:
        lineage = _lineage_summary(derived_from)
        if not lineage:
            return
        blueprint_id = f"blueprint:{lineage['item']}"
        if blueprint_id not in blueprint_nodes:
            blueprint_nodes.add(blueprint_id)
            nodes.append({
                "id": blueprint_id,
                "type": "blueprint",
                "title": lineage["item"],
                "subtitle": f"{lineage['type']} · {lineage['version']}".strip(" ·"),
                "status": lineage["review_status"],
                "details": [
                    {"label": "Source type", "value": lineage["type"]},
                    {"label": "Version", "value": lineage["version"]},
                    {"label": "Path", "value": lineage["path"]},
                    {"label": "Hash", "value": lineage["hash"]},
                ],
            })
        edges.append({"source": blueprint_id, "target": owner_id, "label": "instantiates"})
        if lineage["path"]:
            planning_id = f"planning:{lineage['path']}"
            if planning_id not in planning_nodes:
                planning_nodes.add(planning_id)
                nodes.append({
                    "id": planning_id,
                    "type": "planning_artifact",
                    "title": "Planning artifact",
                    "subtitle": lineage["path"],
                    "status": "",
                    "details": [
                        {"label": "Path", "value": lineage["path"]},
                        {"label": "Hash", "value": lineage["hash"]},
                    ],
                })
            edges.append({"source": planning_id, "target": blueprint_id, "label": "commits"})

    add_lineage_node(f"fr:{rid}", req.get("derived_from"))

    for tbt in fr_tbts:
        tbt_id = str(tbt.get("id") or "")
        if not tbt_id:
            continue
        status = tbt_status_by_id.get(tbt_id, {})
        pack_item = test_pack_by_tbt.get(tbt_id, {})
        test_label, test_meta = _test_node_summary(tbt, status, pack_item)
        test_state = _test_existence_state(tbt, status, pack_item)
        evidence_label, evidence_meta, evidence_state = _evidence_node_summary(status)
        tbt_node_id = f"tbt:{tbt_id}"
        nodes.append({
            "id": tbt_node_id,
            "type": "tbt",
            "title": tbt_id,
            "subtitle": str(tbt.get("title") or "Test basis"),
            "status": str(status.get("status") or tbt.get("lifecycle_status") or ""),
            "details": [
                {"label": "Purpose", "value": str(tbt.get("title") or "")},
                {"label": "Type", "value": str(tbt.get("type") or "")},
                {"label": "Evidence policy", "value": str(tbt.get("evidence_policy") or "")},
            ] + _lineage_context_details(tbt.get("derived_from")),
        })
        edges.append({"source": f"fr:{rid}", "target": tbt_node_id, "label": "proved by"})
        add_lineage_node(tbt_node_id, tbt.get("derived_from"))

        for row in tbt.get("compliance") or []:
            ruleset = str(row.get("ruleset") or "ruleset")
            ref = str(row.get("row") or row.get("row_id") or "")
            row_node_id = f"row:{ruleset}:{ref}"
            if row_node_id not in row_nodes:
                row_nodes.add(row_node_id)
                nodes.append({
                    "id": row_node_id,
                    "type": "ruleset_row",
                    "title": f"{ruleset} {ref}",
                    "subtitle": "Compliance rule",
                    "status": "",
                    "details": [
                        {"label": "Ruleset", "value": ruleset},
                        {"label": "Rule", "value": ref},
                        {"label": "Relationship", "value": str(row.get("relationship") or "satisfies")},
                    ],
                })
            edges.append({"source": tbt_node_id, "target": row_node_id, "label": "maps to"})

        test_node_id = f"test:{tbt_id}"
        nodes.append({
            "id": test_node_id,
            "type": "test",
            "title": test_label,
            "subtitle": test_meta,
            "status": test_label,
            "details": [
                {"label": "State", "value": test_label},
                {"label": "Exists", "value": test_state["exists"]},
                {"label": "Approved", "value": test_state["approved"]},
                {"label": "Path", "value": test_state["path"] or "No test file yet"},
                {"label": "Source", "value": str(pack_item.get("source") or "")},
            ],
        })
        edges.append({"source": tbt_node_id, "target": test_node_id, "label": "implemented by"})

        evidence_node_id = f"evidence:{tbt_id}"
        nodes.append({
            "id": evidence_node_id,
            "type": "test_result",
            "title": evidence_label,
            "subtitle": evidence_meta,
            "status": evidence_state,
            "details": [
                {"label": "Evidence state", "value": evidence_state},
                {"label": "Artifact", "value": evidence_meta},
            ],
        })
        edges.append({"source": test_node_id, "target": evidence_node_id, "label": "produces"})

        scanner_blockers = _scanner_blockers_for_tbt(tbt, scanner_blockers_by_row)
        if scanner_blockers:
            scanner_node_id = f"scanner:{tbt_id}"
            first = scanner_blockers[0]
            first_normalized = first.get("normalized_finding") or {}
            nodes.append({
                "id": scanner_node_id,
                "type": "scanner_result",
                "title": f"{len(scanner_blockers)} mapped scanner finding{'s' if len(scanner_blockers) != 1 else ''}",
                "subtitle": ", ".join(sorted({str(b.get("tool") or (b.get("normalized_finding") or {}).get("scanner") or "scanner") for b in scanner_blockers}))[:120],
                "status": "failed",
                "details": [
                    {"label": "Effect", "value": "Blocks mapped compliance row when failed"},
                    {"label": "First finding", "value": str(first.get("source_locator") or first_normalized.get("location") or "")},
                    {"label": "Mapping", "value": str(first.get("mapping_id") or "")},
                    {"label": "Count", "value": str(len(scanner_blockers))},
                ],
            })
            row_targets = [f"row:{row.get('ruleset') or 'ruleset'}:{row.get('row') or row.get('row_id') or ''}" for row in tbt.get("compliance") or []]
            for row_node_id in row_targets:
                if row_node_id in row_nodes:
                    edges.append({"source": row_node_id, "target": scanner_node_id, "label": "scanner evidence"})
    return {"nodes": nodes, "edges": edges}


def _test_node_summary(tbt: dict, status: dict, pack_item: dict) -> tuple[str, str]:
    state = _test_existence_state(tbt, status, pack_item)
    return state["label"], state["path"] or state["detail"]


def _evidence_node_summary(status: dict) -> tuple[str, str, str]:
    state = str(status.get("status") or "missing")
    observed = status.get("observed_evidence") or []
    if observed:
        first = observed[0]
        source = first.get("source_locator") or first.get("source") or first.get("id") or "observed artifact"
        return "Observed", str(source), state
    return "Missing", "No observed artifact in this scan", state


def _compliance_node_summary(rows: list[dict]) -> str:
    if not rows:
        return '<strong>Not mapped</strong><em>No compliance rule edge declared</em>'
    items = []
    for row in rows[:4]:
        ruleset = row.get("ruleset") or "ruleset"
        ref = row.get("row") or ""
        items.append(f'<b>{html.escape(str(ruleset))}</b> <code>{html.escape(str(ref))}</code>')
    if len(rows) > 4:
        items.append(f'<em>and {len(rows) - 4} more</em>')
    return "".join(f'<div>{item}</div>' for item in items)


def _scanner_node_summary(scanner_blockers: list[dict]) -> str:
    if not scanner_blockers:
        return '<strong>No mapped finding</strong><em>No direct scanner result is attached to this TBT&apos;s compliance rows.</em>'
    items = []
    for blocker in scanner_blockers[:3]:
        normalized = blocker.get("normalized_finding") or {}
        tool = blocker.get("tool") or normalized.get("scanner") or "scanner"
        rule = normalized.get("rule_id") or blocker.get("rule_id") or blocker.get("mapping_id") or ""
        status = blocker.get("status") or "failed"
        locator = blocker.get("source_locator") or normalized.get("location") or ""
        items.append(
            '<div class="fr-local-scan-hit">'
            f'<strong>{html.escape(str(tool))} {html.escape(str(status))}</strong>'
            f'{f"<code>{html.escape(str(rule))}</code>" if rule else ""}'
            f'{f"<em>{html.escape(short_text(str(locator), 72))}</em>" if locator else ""}'
            '</div>'
        )
    if len(scanner_blockers) > 3:
        items.append(f'<em>and {len(scanner_blockers) - 3} more mapped finding(s)</em>')
    return "".join(items)


def _scanner_blockers_for_tbt(tbt: dict, scanner_blockers_by_row: dict[str, list[dict]]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for row in tbt.get("compliance") or []:
        for key in _compliance_row_keys(row):
            for blocker in scanner_blockers_by_row.get(key, []):
                blocker_id = str(blocker.get("id") or blocker.get("source_locator") or blocker.get("source") or "")
                if blocker_id in seen:
                    continue
                seen.add(blocker_id)
                out.append(blocker)
    return out


def _test_existence_state(tbt: dict, status: dict, pack_item: dict) -> dict[str, str]:
    observed = status.get("observed_evidence") or []
    pack_path = str(pack_item.get("pack_path") or "")
    planned_path = str(tbt.get("ref") or "")
    actual_path = pack_path or planned_path
    exists = bool(pack_item.get("pack_path") or pack_item.get("source") in {"generated", "existing_asvs", "native"})
    approved = pack_item.get("status") == "ready_to_run" and pack_item.get("safety") == "non_destructive"
    if observed:
        label = "Evidence observed"
    elif approved:
        label = "Approved for scan"
    elif exists:
        label = "Awaiting approval"
    else:
        label = "No test yet"
    detail_bits = []
    if exists:
        detail_bits.append("file exists")
    elif planned_path:
        detail_bits.append("planned path declared")
    else:
        detail_bits.append("no path declared")
    source = pack_item.get("source")
    if source:
        detail_bits.append(str(source))
    policy = tbt.get("evidence_policy")
    if policy:
        detail_bits.append(str(policy))
    return {
        "label": label,
        "path": actual_path,
        "detail": " · ".join(detail_bits),
        "exists": "yes" if exists else "no",
        "approved": "yes" if approved else "no",
    }


def _render_assurance_chain_table(
    req: dict,
    fr_tbts: list[dict],
    tbt_status_by_id: dict[str, dict],
    test_pack_by_tbt: dict[str, dict],
) -> str:
    if not fr_tbts:
        return (
            '<div class="fr-chain-empty">'
            'No Test Basis records are declared for this FR yet.'
            '</div>'
        )
    rows = []
    for tbt in fr_tbts:
        tbt_id = str(tbt.get("id") or "")
        status = tbt_status_by_id.get(tbt_id, {})
        pack_item = test_pack_by_tbt.get(tbt_id, {})
        rows.append(
            '<tr>'
            f'<td><code>{html.escape(tbt_id)}</code><div class="fr-chain-subtle">{html.escape(str(tbt.get("type") or "test"))}</div></td>'
            f'<td>{html.escape(str(tbt.get("title") or "Untitled test basis"))}</td>'
            f'<td>{_compliance_badges(tbt.get("compliance") or [])}</td>'
            f'<td>{_test_state_text(tbt, status, pack_item)}</td>'
            f'<td>{_evidence_state_text(status)}</td>'
            '</tr>'
        )
    return (
        '<div class="fr-chain-table-wrap">'
        '<table class="fr-chain-table">'
        '<thead><tr>'
        '<th>TBT</th><th>Purpose</th><th>Compliance</th><th>Test state</th><th>Evidence</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _compliance_badges(rows: list[dict]) -> str:
    if not rows:
        return '<span class="fr-chain-muted">Not mapped</span>'
    badges = []
    for row in rows:
        ruleset = row.get("ruleset") or "ruleset"
        ref = row.get("row") or ""
        relationship = row.get("relationship")
        rel = f' <em>{html.escape(str(relationship))}</em>' if relationship and relationship != "satisfies" else ""
        badges.append(
            f'<span class="fr-chain-compliance"><strong>{html.escape(str(ruleset))}</strong> {html.escape(str(ref))}{rel}</span>'
        )
    return "".join(badges)


def _test_state_text(tbt: dict, status: dict, pack_item: dict) -> str:
    state = _test_existence_state(tbt, status, pack_item)
    pack_path = state["path"]
    path_html = f'<div class="fr-chain-subtle"><code>{html.escape(str(pack_path))}</code></div>' if pack_path else ""
    return f'<span>{html.escape(state["label"])}</span>{path_html}<div class="fr-chain-subtle">{html.escape(state["detail"])}</div>'


def _evidence_state_text(status: dict) -> str:
    state = str(status.get("status") or "missing")
    label, title = _assurance_badge_copy(state)
    observed = status.get("observed_evidence") or []
    if observed:
        evidence = _observed_evidence_text(observed)
    else:
        evidence = '<span class="fr-chain-muted">No observed evidence in this scan</span>'
    return (
        f'<span class="fr-evidence-state assurance-state-{html.escape(state)}" title="{html.escape(title)}">{html.escape(label)}</span>'
        f'<div class="fr-chain-evidence">{evidence}</div>'
    )


def _source_from_description(description: str) -> str:
    match = re.search(r"Source:\s*([^.;]+(?:[.-][^.;]+)*)", description)
    return match.group(1).strip() if match else ""


def _gate_from_description(description: str) -> str:
    match = re.search(r"Gate:\s*([^.;]+)", description)
    return match.group(1).strip() if match else ""


def _trace_from_description(description: str) -> str:
    match = re.search(r"Trace:\s*([^.;]+(?:;\s*[^.;]+)*)", description)
    return match.group(1).strip() if match else ""


def _compliance_row_keys(row: dict) -> list[str]:
    ruleset = str(row.get("ruleset") or "")
    ref = str(row.get("row") or row.get("row_id") or "")
    keys = []
    if ruleset and ref:
        keys.append(f"{ruleset}:{ref}")
        keys.append(f"row:{ruleset}:{ref}")
    if ref:
        keys.append(ref)
    return keys


def _scanner_blockers_by_fr(assurance_status: dict) -> dict[str, list[dict]]:
    blockers_by_fr: dict[str, list[dict]] = {}
    seen_by_fr: dict[str, set[str]] = {}
    for row in assurance_status.get("compliance_rows") or []:
        row_id = row.get("id") or ":".join(str(v) for v in [row.get("ruleset"), row.get("row_id")] if v)
        blockers = row.get("scanner_blockers") or []
        if not row_id or not blockers:
            continue
        for fr_id in row.get("fr_refs") or []:
            bucket = blockers_by_fr.setdefault(fr_id, [])
            seen = seen_by_fr.setdefault(fr_id, set())
            for blocker in blockers:
                blocker_id = str(blocker.get("id") or blocker.get("source_locator") or blocker.get("source") or "")
                key = f"{row_id}:{blocker_id}"
                if key in seen:
                    continue
                seen.add(key)
                bucket.append({"row_id": row_id, **blocker})
    return blockers_by_fr


def _scanner_blockers_by_row(assurance_status: dict) -> dict[str, list[dict]]:
    blockers_by_row: dict[str, list[dict]] = {}
    for row in assurance_status.get("compliance_rows") or []:
        row_id = str(row.get("id") or "")
        ruleset = str(row.get("ruleset") or "")
        ref = str(row.get("row_id") or row.get("row") or "")
        keys = [key for key in [row_id, ref, f"{ruleset}:{ref}" if ruleset and ref else "", f"row:{ruleset}:{ref}" if ruleset and ref else ""] if key]
        for key in keys:
            blockers_by_row.setdefault(key, []).extend(row.get("scanner_blockers") or [])
    return blockers_by_row


def _render_scanner_blockers(blockers: list[dict]) -> str:
    if not blockers:
        return ""
    items = []
    for blocker in blockers[:8]:
        normalized = blocker.get("normalized_finding") or {}
        tool = blocker.get("tool") or normalized.get("scanner") or "scanner"
        mapping = blocker.get("mapping_id") or ""
        rule = normalized.get("rule_id") or blocker.get("rule_id") or ""
        locator = blocker.get("source_locator") or normalized.get("location") or blocker.get("source") or ""
        message = normalized.get("message") or blocker.get("message") or ""
        status = blocker.get("status") or "failed"
        row_id = blocker.get("row_id") or ""
        items.append(
            '<li>'
            f'<code>{html.escape(str(row_id))}</code> '
            f'<span class="fr-evidence-state assurance-state-{html.escape(str(status))}">{html.escape(str(status))}</span> '
            f'<code>{html.escape(str(tool))}</code>'
            f'{f" <code>{html.escape(str(rule))}</code>" if rule else ""}'
            f'{f"<div class=\"manual-evidence\">Mapping: {html.escape(str(mapping))}</div>" if mapping else ""}'
            f'{f"<div class=\"manual-evidence\">{html.escape(str(locator))}</div>" if locator else ""}'
            f'{f"<div>{html.escape(short_text(str(message), 160))}</div>" if message else ""}'
            '</li>'
        )
    if len(blockers) > 8:
        items.append(f'<li><em>and {len(blockers) - 8} more scanner blocker(s)</em></li>')
    return (
        '<div class="fr-detail-section fr-scanner-blockers">'
        '<strong>Scanner blockers:</strong>'
        '<div class="manual-evidence">Direct scanner-to-compliance mappings are independent evidence. '
        'A failing direct scanner result blocks the mapped compliance row even when a bespoke TBT has passing evidence.</div>'
        f'<ul class="fr-evidence-mini-list">{"".join(items)}</ul>'
        '</div>'
    )


def _assurance_badge_copy(state: str | None) -> tuple[str, str]:
    """Human-facing copy for resolver states in the FR catalog table."""
    state = str(state or "unknown")
    labels = {
        "passed": "proved",
        "partial": "partial",
        "manual_review": "review",
        "missing": "unproven",
        "failed": "failed",
        "waived": "waived",
        "compensating_control": "control",
        "out_of_scope": "out scope",
    }
    titles = {
        "passed": "Resolved assurance: observed evidence currently proves this FR.",
        "partial": "Resolved assurance: some evidence exists, but the chain is not sufficient yet.",
        "manual_review": "Resolved assurance: human review or manual evidence is required.",
        "missing": "Resolved assurance: this FR has declared TBTs, but no sufficient observed evidence was found in this scan.",
        "failed": "Resolved assurance: failing evidence was observed for this FR.",
        "waived": "Resolved assurance: this FR has waiver handling and should not be counted as proved.",
        "compensating_control": "Resolved assurance: this FR relies on a compensating control.",
        "out_of_scope": "Resolved assurance: this FR is outside the selected assurance scope.",
    }
    return labels.get(state, state), titles.get(state, f"Resolved assurance status: {state}")


def _render_fr_evidence_matrix(assurance: dict) -> str:
    tbt_statuses = assurance.get("tbt_statuses") or []
    if not tbt_statuses:
        return ""
    rows: list[str] = []
    for item in tbt_statuses:
        state = str(item.get("status", "missing"))
        label, title = _assurance_badge_copy(state)
        reqs = item.get("requirements") or []
        observed = item.get("observed_evidence") or []
        req_text = _evidence_requirement_text(reqs)
        obs_text = _observed_evidence_text(observed)
        rows.append(
            '<tr>'
            f'<td><code>{html.escape(str(item.get("id", "")))}</code>'
            f'<div class="manual-evidence">{html.escape(str(item.get("type") or ""))}'
            f'{(" · " + html.escape(str(item.get("evidence_policy")))) if item.get("evidence_policy") else ""}</div></td>'
            f'<td><span class="fr-evidence-state assurance-state-{html.escape(state)}" title="{html.escape(title)}">{html.escape(label)}</span></td>'
            f'<td>{req_text}</td>'
            f'<td>{obs_text}</td>'
            '</tr>'
        )
    return (
        '<div class="fr-detail-section fr-evidence-matrix">'
        '<strong>Evidence state:</strong>'
        '<table class="fr-evidence-table"><thead><tr>'
        '<th>TBT</th><th>Status</th><th>Expected evidence</th><th>Observed evidence</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _evidence_requirement_text(requirements: list[dict]) -> str:
    if not requirements:
        return '<span class="muted">No expected evidence declared yet</span>'
    bits = []
    for req in requirements[:4]:
        inferred = ' <em>inferred</em>' if req.get("inferred") else ""
        strength = req.get("strength") or req.get("minimum_strength") or ""
        source = req.get("source") or ""
        label = req.get("type") or "evidence"
        suffix = []
        if strength:
            suffix.append(strength)
        if source:
            suffix.append(source)
        meta = f' <span class="manual-evidence">{" · ".join(html.escape(str(v)) for v in suffix)}{inferred}</span>' if suffix or inferred else ""
        bits.append(f'<li>{html.escape(str(label))}{meta}</li>')
    if len(requirements) > 4:
        bits.append(f'<li><em>and {len(requirements) - 4} more</em></li>')
    return f'<ul class="fr-evidence-mini-list">{"".join(bits)}</ul>'


def _observed_evidence_text(records: list[dict]) -> str:
    if not records:
        return '<span class="muted">No observed artifact in this scan</span>'

    def artifact_label(item: dict | str) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            label = str(item.get("path") or item.get("locator") or item.get("source") or item.get("id") or "")
            schema_ref = str(item.get("schema_ref") or "")
            return f"{label} · schema: {schema_ref}" if label and schema_ref else label
        return str(item)

    def side_effect_label(item: dict | str) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            kind = str(item.get("type") or "side_effect").replace("_", " ")
            target = str(item.get("target") or "")
            mode = str(item.get("mode") or "").replace("_", " ")
            return " · ".join(part for part in [kind, target, mode] if part)
        return str(item)

    bits = []
    for record in records[:4]:
        status = record.get("status") or "observed"
        source = record.get("source_locator") or record.get("source") or record.get("id") or ""
        strength = record.get("strength") or ""
        meta = " · ".join(html.escape(str(v)) for v in [status, strength] if v)
        inputs = [artifact_label(item) for item in (record.get("inputs") or [])[:2] if artifact_label(item)]
        outputs = [artifact_label(item) for item in (record.get("outputs") or [])[:2] if artifact_label(item)]
        effects = [side_effect_label(item) for item in (record.get("side_effects") or [])[:2] if side_effect_label(item)]
        actions = [
            " · ".join(
                part for part in [
                    str(item.get("type") or "").replace("_", " "),
                    str(item.get("name") or ""),
                    str(item.get("status") or ""),
                ]
                if part
            )
            for item in (record.get("test_actions") or [])[:2]
            if isinstance(item, dict)
        ]
        io_bits = []
        if inputs:
            io_bits.append("Inputs: " + ", ".join(inputs))
        if outputs:
            io_bits.append("Outputs: " + ", ".join(outputs))
        if effects:
            io_bits.append("Side effects: " + ", ".join(effects))
        if actions:
            io_bits.append("Test actions: " + ", ".join(actions))
        io_html = f'<div class="manual-evidence">{html.escape(" | ".join(io_bits))}</div>' if io_bits else ""
        bits.append(
            f'<li><code>{html.escape(str(record.get("id") or source or "evidence"))}</code>'
            f'{f" <span class=\"manual-evidence\">{meta}</span>" if meta else ""}'
            f'{f"<div class=\"manual-evidence\">{html.escape(str(source))}</div>" if source else ""}'
            f'{io_html}</li>'
        )
    if len(records) > 4:
        bits.append(f'<li><em>and {len(records) - 4} more</em></li>')
    return f'<ul class="fr-evidence-mini-list">{"".join(bits)}</ul>'


def _fr_catalog_error(message: str) -> str:
    return (
        '<section class="card"><div class="callout"><strong>FR catalog error:</strong><br>'
        f'{html.escape(message)}<br><br>'
        'Fix the catalog and rescan.</div></section>'
    )


# ===========================================================================
