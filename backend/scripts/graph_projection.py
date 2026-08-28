#!/usr/bin/env python3
"""Small graph projection helpers for dashboard/report payloads.

The runtime graph is the source of truth. This module keeps derived view
summaries as pure functions over normalized graph data so dashboard generation
does not grow another independent truth model.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in graph.get("nodes") or [] if isinstance(node, dict)]


def _edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [edge for edge in graph.get("edges") or [] if isinstance(edge, dict)]


def _metadata(node: dict[str, Any]) -> dict[str, Any]:
    metadata = node.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _node_value(node: dict[str, Any], key: str, fallback: Any = None) -> Any:
    value = node.get(key)
    if value not in (None, ""):
        return value
    return _metadata(node).get(key, fallback)


def node_type_counts(graph: dict[str, Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(node.get("type") or "unknown") for node in _nodes(graph)).items()))


def edge_type_counts(graph: dict[str, Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(edge.get("type") or "unknown") for edge in _edges(graph)).items()))


def graph_overview(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = _nodes(graph)
    edges = _edges(graph)
    status_counts = Counter(str(_node_value(node, "status", "unknown")) for node in nodes)
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_type_counts": node_type_counts(graph),
        "edge_type_counts": edge_type_counts(graph),
        "status_counts": dict(sorted(status_counts.items())),
    }


def project_fr_projection(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = _nodes(graph)
    fr_nodes = [node for node in nodes if node.get("type") == "fr" and not _node_value(node, "ghost")]
    tbt_nodes = [node for node in nodes if node.get("type") == "tbt" and not _node_value(node, "ghost")]
    gap_fr_nodes = [node for node in nodes if node.get("type") == "fr" and _node_value(node, "ghost")]
    gap_tbt_nodes = [node for node in nodes if node.get("type") == "tbt" and _node_value(node, "ghost")]
    evidence_nodes = [node for node in nodes if node.get("type") == "evidence"]
    scanner_nodes = scanner_evidence_nodes(graph)
    scanner_summary = scanner_evidence_projection(graph)
    by_fr_status = Counter(str(_node_value(node, "status", "unknown")) for node in fr_nodes)
    by_tbt_status = Counter(str(_node_value(node, "status", "unknown")) for node in tbt_nodes)
    return {
        "source": "runtime_graph",
        "fr_count": len(fr_nodes),
        "tbt_count": len(tbt_nodes),
        "evidence_count": len(evidence_nodes),
        "scanner_evidence_count": len(scanner_nodes),
        "scanner_direct_blocker_count": scanner_summary["direct_blocker_count"],
        "scanner_mapped_signal_count": scanner_summary["mapped_signal_count"],
        "scanner_domain_signal_count": scanner_summary["domain_signal_count"],
        "scanner_unmapped_inventory_count": scanner_summary["unmapped_inventory_count"],
        "missing_fr_gap_count": len(gap_fr_nodes),
        "missing_tbt_gap_count": len(gap_tbt_nodes),
        "fr_status_counts": dict(sorted(by_fr_status.items())),
        "tbt_status_counts": dict(sorted(by_tbt_status.items())),
    }


def scanner_evidence_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        node for node in _nodes(graph)
        if node.get("type") == "evidence"
        and (
            _node_value(node, "evidence_type") == "scanner_result"
            or _node_value(node, "scanner")
            or _node_value(node, "tool")
            or str(node.get("id", "")).startswith("evidence:scanner")
        )
    ]


def scanner_evidence_blocks(node: dict[str, Any]) -> bool:
    status = str(_node_value(node, "status", "")).lower()
    role = str(_node_value(node, "evidence_role", "")).lower()
    effect = str(_node_value(node, "assurance_effect", "")).lower()
    mapping_level = str(_node_value(node, "mapping_level", "")).lower()
    return status == "failed" and (
        "blocking" in role
        or "blocking" in effect
        or mapping_level == "compliance_row"
    )


def _scanner_evidence_summary(node: dict[str, Any]) -> dict[str, Any]:
    normalized = _node_value(node, "normalized_finding", {}) or {}
    if not isinstance(normalized, dict):
        normalized = {}
    return {
        "id": node.get("id", ""),
        "type": "scanner_result",
        "status": _node_value(node, "status", "unknown"),
        "strength": _node_value(node, "evidence_strength", _node_value(node, "strength", "")),
        "tool": _node_value(node, "scanner", _node_value(node, "tool", normalized.get("scanner", ""))),
        "mapping_id": _node_value(node, "ref", _node_value(node, "mapping_id", "")),
        "assurance_effect": _node_value(node, "assurance_effect", ""),
        "traceability_strength": _node_value(node, "traceability_strength", ""),
        "mapping_level": _node_value(node, "mapping_level", ""),
        "confidence": _node_value(node, "confidence", ""),
        "source": _node_value(node, "source", ""),
        "source_locator": _node_value(node, "source_locator", normalized.get("location", "")),
        "rule_id": _node_value(node, "rule_id", normalized.get("rule_id", "")),
        "message": _node_value(node, "message", normalized.get("message", "")),
        "matched_finding_count": _node_value(node, "matched_finding_count", 0),
        "blocks_compliance": scanner_evidence_blocks(node),
        "normalized_finding": normalized,
    }


def scanner_evidence_projection(graph: dict[str, Any]) -> dict[str, Any]:
    scanner_nodes = scanner_evidence_nodes(graph)
    direct_blockers = [node for node in scanner_nodes if scanner_evidence_blocks(node)]
    mapped_signals = [
        node for node in scanner_nodes
        if _node_value(node, "mapping_level") == "compliance_row"
    ]
    domain_signals = [
        node for node in scanner_nodes
        if _node_value(node, "mapping_level") == "compliance_domain"
    ]
    unmapped_inventory = [
        node for node in scanner_nodes
        if _node_value(node, "mapping_level") == "general_finding"
        or _node_value(node, "traceability_strength") == "unmapped"
    ]
    by_scanner = Counter(str(_node_value(node, "scanner", _node_value(node, "tool", "unknown"))) for node in scanner_nodes)
    by_status = Counter(str(_node_value(node, "status", "unknown")) for node in scanner_nodes)
    by_mapping_level = Counter(str(_node_value(node, "mapping_level", "unmapped")) for node in scanner_nodes)
    return {
        "source": "runtime_graph",
        "scanner_evidence_count": len(scanner_nodes),
        "direct_blocker_count": len(direct_blockers),
        "mapped_signal_count": len(mapped_signals),
        "domain_signal_count": len(domain_signals),
        "unmapped_inventory_count": len(unmapped_inventory),
        "scanner_counts": dict(sorted(by_scanner.items())),
        "status_counts": dict(sorted(by_status.items())),
        "mapping_level_counts": dict(sorted(by_mapping_level.items())),
        "direct_blockers": [
            {
                "id": node.get("id"),
                "scanner": _node_value(node, "scanner", _node_value(node, "tool", "")),
                "ruleset": _node_value(node, "ruleset", ""),
                "row": _node_value(node, "row", ""),
                "mapping_id": _node_value(node, "ref", ""),
                "source_locator": _node_value(node, "source_locator", ""),
                "matched_finding_count": _node_value(node, "matched_finding_count", 0),
            }
            for node in direct_blockers[:50]
        ],
    }


def _ruleset_ui_state(status: str) -> str:
    return {
        "passed": "satisfied",
        "satisfied": "satisfied",
        "partial": "partial",
        "manual_review": "partial",
        "waived": "partial",
        "compensating_control": "partial",
        "failed": "failed",
        "missing": "unaddressed",
        "unaddressed": "unaddressed",
        "out_of_scope": "filtered",
        "filtered": "filtered",
        "not_applicable": "na",
        "na": "na",
    }.get(status or "", status or "unaddressed")


def ruleset_projection(graph: dict[str, Any]) -> dict[str, Any]:
    row_nodes = [
        node for node in _nodes(graph)
        if node.get("type") == "ruleset_row"
        and not _node_value(node, "ghost")
    ]
    by_ruleset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    row_ids = {str(node.get("id", "")) for node in row_nodes if node.get("id")}
    scanner_nodes = scanner_evidence_nodes(graph)
    scanner_by_row_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in scanner_nodes:
        ruleset = str(_node_value(node, "ruleset", "") or "").strip()
        row = str(_node_value(node, "row", "") or "").strip()
        if ruleset and row:
            scanner_by_row_id[f"{ruleset}:{row}"].append(_scanner_evidence_summary(node))
    node_by_id = {str(node.get("id", "")): node for node in _nodes(graph)}
    for edge in _edges(graph):
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        source_node = node_by_id.get(source)
        target_node = node_by_id.get(target)
        if source_node in scanner_nodes and target in row_ids:
            scanner_by_row_id[target].append(_scanner_evidence_summary(source_node))
        elif target_node in scanner_nodes and source in row_ids:
            scanner_by_row_id[source].append(_scanner_evidence_summary(target_node))
    for node in row_nodes:
        ruleset = str(_node_value(node, "ruleset", "") or "").strip() or "unknown"
        status = str(_node_value(node, "status", "unaddressed"))
        scanner_blockers = _node_value(node, "scanner_blockers", []) or []
        scanner_evidence = []
        seen_scanner: set[str] = set()
        for item in [*scanner_by_row_id.get(str(node.get("id", "")), []), *scanner_blockers]:
            if not isinstance(item, dict):
                continue
            summary = item if item.get("type") == "scanner_result" else {
                "id": item.get("id", ""),
                "type": "scanner_result",
                "status": item.get("status", "failed"),
                "strength": item.get("strength", item.get("evidence_strength", "")),
                "tool": item.get("tool", item.get("scanner", "")),
                "mapping_id": item.get("mapping_id", item.get("ref", "")),
                "assurance_effect": item.get("assurance_effect", ""),
                "traceability_strength": item.get("traceability_strength", ""),
                "mapping_level": item.get("mapping_level", "compliance_row"),
                "confidence": item.get("confidence", ""),
                "source": item.get("source", ""),
                "source_locator": item.get("source_locator", ""),
                "rule_id": item.get("rule_id", ""),
                "message": item.get("message", ""),
                "matched_finding_count": item.get("matched_finding_count", 0),
                "blocks_compliance": True,
                "normalized_finding": item.get("normalized_finding", {}) or {},
            }
            key = str(summary.get("mapping_id") or summary.get("source_locator") or summary.get("id") or summary)
            if key in seen_scanner:
                continue
            seen_scanner.add(key)
            scanner_evidence.append(summary)
        derived_blockers = [item for item in scanner_evidence if item.get("blocks_compliance")]
        scanner_blockers_out = derived_blockers or scanner_blockers
        if derived_blockers and status in {"", "missing", "unaddressed", "not_observed"}:
            status = "failed"
        scanner_evidence.sort(key=lambda item: (
            0 if item.get("blocks_compliance") else 1,
            str(item.get("tool") or ""),
            str(item.get("mapping_id") or ""),
            str(item.get("source_locator") or ""),
        ))
        by_ruleset[ruleset].append({
            "id": node.get("id", ""),
            "ruleset": ruleset,
            "row": _node_value(node, "row", ""),
            "chapter": _node_value(node, "chapter", ""),
            "status": status,
            "ui_state": _ruleset_ui_state(status),
            "frs": _node_value(node, "frs", []) or [],
            "tbts": _node_value(node, "tbts", []) or [],
            "scanner_evidence_count": len(scanner_evidence),
            "scanner_evidence": scanner_evidence[:8],
            "scanner_blocker_count": len(scanner_blockers_out),
            "scanner_blockers": scanner_blockers_out[:5],
            "reasons": (_node_value(node, "reasons", []) or [])[:8],
        })

    rulesets: dict[str, dict[str, Any]] = {}
    for ruleset, rows in sorted(by_ruleset.items()):
        status_counts = Counter(str(row.get("status", "unknown")) for row in rows)
        ui_state_counts = Counter(str(row.get("ui_state", "unknown")) for row in rows)
        blocker_count = sum(int(row.get("scanner_blocker_count", 0)) for row in rows)
        scanner_evidence_count = sum(int(row.get("scanner_evidence_count", 0)) for row in rows)
        rulesets[ruleset] = {
            "source": "runtime_graph",
            "row_count": len(rows),
            "status_counts": dict(sorted(status_counts.items())),
            "ui_state_counts": dict(sorted(ui_state_counts.items())),
            "scanner_evidence_count": scanner_evidence_count,
            "rows_with_scanner_evidence": sum(1 for row in rows if row.get("scanner_evidence_count")),
            "scanner_blocker_count": blocker_count,
            "rows_with_scanner_blockers": sum(1 for row in rows if row.get("scanner_blocker_count")),
            "rows": sorted(rows, key=lambda row: str(row.get("row", ""))),
        }

    return {
        "source": "runtime_graph",
        "ruleset_count": len(rulesets),
        "row_count": len(row_nodes),
        "rulesets": rulesets,
    }


def evidence_files_projection(graph: dict[str, Any]) -> dict[str, Any]:
    evidence_nodes = [
        node for node in _nodes(graph)
        if node.get("type") == "evidence"
        and not _node_value(node, "ghost")
    ]
    by_type = Counter(str(_node_value(node, "evidence_type", "unknown")) for node in evidence_nodes)
    by_status = Counter(str(_node_value(node, "status", "unknown")) for node in evidence_nodes)
    by_strength = Counter(str(_node_value(node, "evidence_strength", "unknown")) for node in evidence_nodes)
    scanner_nodes = scanner_evidence_nodes(graph)
    test_result_nodes = [
        node for node in evidence_nodes
        if _node_value(node, "evidence_type") in {"test_result", "result"}
    ]
    manual_nodes = [
        node for node in evidence_nodes
        if _node_value(node, "evidence_type") in {"document", "approval", "screenshot", "manual_note", "evidence"}
    ]
    artifact_refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for node in evidence_nodes:
        source = str(_node_value(node, "source", "") or "")
        source_locator = str(_node_value(node, "source_locator", "") or "")
        ref = source_locator or source or str(_node_value(node, "ref", "") or "")
        if not ref:
            continue
        key = (str(node.get("id", "")), ref)
        if key in seen:
            continue
        seen.add(key)
        artifact_refs.append({
            "node_id": node.get("id", ""),
            "label": node.get("label", ""),
            "ref": ref,
            "source": source,
            "source_locator": source_locator,
            "evidence_type": _node_value(node, "evidence_type", "unknown"),
            "status": _node_value(node, "status", "unknown"),
            "scanner": _node_value(node, "scanner", _node_value(node, "tool", "")),
            "scanner_health": _node_value(node, "scanner_health", ""),
            "scanner_reason": _node_value(node, "scanner_reason", ""),
            "ruleset": _node_value(node, "ruleset", ""),
            "row": _node_value(node, "row", ""),
            "domain": _node_value(node, "domain", ""),
            "mapping_level": _node_value(node, "mapping_level", ""),
            "traceability_strength": _node_value(node, "traceability_strength", ""),
            "evidence_role": _node_value(node, "evidence_role", ""),
            "inputs": _node_value(node, "inputs", []),
            "outputs": _node_value(node, "outputs", []),
            "side_effects": _node_value(node, "side_effects", []),
            "test_actions": _node_value(node, "test_actions", []),
        })
    return {
        "source": "runtime_graph",
        "evidence_count": len(evidence_nodes),
        "scanner_evidence_count": len(scanner_nodes),
        "test_result_count": len(test_result_nodes),
        "manual_evidence_count": len(manual_nodes),
        "status_counts": dict(sorted(by_status.items())),
        "evidence_type_counts": dict(sorted(by_type.items())),
        "evidence_strength_counts": dict(sorted(by_strength.items())),
        "artifact_ref_count": len(artifact_refs),
        "artifact_refs": artifact_refs[:100],
    }


def assurance_projection(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = _nodes(graph)
    process_types = {"process", "gate", "criterion", "role", "approval", "waiver", "compensating_control", "decision"}
    counts = Counter(str(node.get("type") or "unknown") for node in nodes if node.get("type") in process_types)
    statuses: dict[str, Counter[str]] = defaultdict(Counter)
    for node in nodes:
        node_type = str(node.get("type") or "")
        if node_type not in process_types:
            continue
        status = str(
            _node_value(node, "status")
            or _node_value(node, "readiness_status")
            or _node_value(node, "approval_status")
            or "unknown"
        )
        statuses[node_type][status] += 1
    return {
        "source": "runtime_graph",
        "node_counts": dict(sorted(counts.items())),
        "status_counts": {
            node_type: dict(sorted(counter.items()))
            for node_type, counter in sorted(statuses.items())
        },
    }


def lineage_projection(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = _nodes(graph)
    edges = _edges(graph)
    planning_nodes = [node for node in nodes if node.get("type") == "planning_artifact"]
    blueprint_nodes = [node for node in nodes if node.get("type") == "blueprint"]
    derived_edges = [edge for edge in edges if edge.get("type") == "derived_from"]
    by_planning_role = Counter(str(_node_value(node, "role", "unknown")) for node in planning_nodes)
    by_blueprint_type = Counter(str(_node_value(node, "source_type", "unknown")) for node in blueprint_nodes)
    blueprint_ids = {str(node.get("id", "")) for node in blueprint_nodes}
    planning_ids = {str(node.get("id", "")) for node in planning_nodes}
    project_to_blueprint_edges = [
        edge for edge in derived_edges
        if str(edge.get("target", "")) in blueprint_ids
    ]
    blueprint_to_planning_edges = [
        edge for edge in derived_edges
        if str(edge.get("source", "")) in blueprint_ids
        and str(edge.get("target", "")) in planning_ids
    ]
    return {
        "source": "runtime_graph",
        "planning_artifact_count": len(planning_nodes),
        "blueprint_node_count": len(blueprint_nodes),
        "derived_from_edge_count": len(derived_edges),
        "project_to_blueprint_edge_count": len(project_to_blueprint_edges),
        "blueprint_to_planning_edge_count": len(blueprint_to_planning_edges),
        "planning_role_counts": dict(sorted(by_planning_role.items())),
        "blueprint_type_counts": dict(sorted(by_blueprint_type.items())),
        "planning_artifacts": [
            {
                "id": node.get("id", ""),
                "role": _node_value(node, "role", ""),
                "path": _node_value(node, "path", ""),
                "sha256": _node_value(node, "sha256", ""),
                "schema": _node_value(node, "schema", ""),
                "status": _node_value(node, "artifact_status", _node_value(node, "status", "")),
            }
            for node in sorted(planning_nodes, key=lambda item: str(item.get("id", "")))[:100]
        ],
    }


def graph_projections(graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "overview": graph_overview(graph),
        "project_frs": project_fr_projection(graph),
        "scanner_evidence": scanner_evidence_projection(graph),
        "rulesets": ruleset_projection(graph),
        "evidence_files": evidence_files_projection(graph),
        "assurance": assurance_projection(graph),
        "lineage": lineage_projection(graph),
    }
