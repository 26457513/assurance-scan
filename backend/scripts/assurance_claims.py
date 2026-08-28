"""Shared assurance-claim evaluation and export helpers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from artifact_hashing import file_sha256


SATISFIED_STATUSES = {"passed", "satisfied", "waived", "compensating_control"}
UNSATISFIED_STATUSES = {"failed", "missing", "partial", "blocked", "manual_review", "unaddressed"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def node_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node.get("id")): node for node in graph.get("nodes") or []}


def node_value(node: dict[str, Any], key: str, fallback: Any = None) -> Any:
    value = node.get(key)
    if value not in (None, ""):
        return value
    metadata = node.get("metadata") or {}
    return metadata.get(key, fallback)


def candidate_target_ids(claim_type: str, target: str) -> list[str]:
    if claim_type == "fr_satisfied":
        return [target if target.startswith("fr:") else f"fr:{target}"]
    if claim_type == "tbt_satisfied":
        return [target if target.startswith("test:") else f"test:{target}"]
    if claim_type == "no_blocking_scanner_evidence":
        if target.startswith("FR-"):
            return [f"fr:{target}"]
        if target.startswith("TBT-"):
            return [f"test:{target}"]
        if target.startswith(("fr:", "test:")):
            return [target]
    if claim_type in {"compliance_row_satisfied", "no_blocking_scanner_evidence"}:
        if ":" in target:
            return [target]
        return [f"ASVS:{target}", f"ASVS:v{target}" if not target.startswith("v") else f"ASVS:{target}"]
    return [target]


def find_target_node(graph: dict[str, Any], claim_type: str, target: str) -> dict[str, Any] | None:
    nodes = node_by_id(graph)
    for node_id in candidate_target_ids(claim_type, target):
        if node_id in nodes:
            return nodes[node_id]
    for node in nodes.values():
        metadata = node.get("metadata") or {}
        if target in {metadata.get("fr_id"), metadata.get("tbt"), metadata.get("ref"), metadata.get("row")}:
            return node
    return None


def graph_edges_for_target(graph: dict[str, Any], target_id: str) -> list[dict[str, Any]]:
    return [
        edge for edge in graph.get("edges") or []
        if edge.get("source") == target_id or edge.get("target") == target_id
    ]


def evidence_refs_for_target(graph: dict[str, Any], target_id: str) -> list[str]:
    refs: set[str] = set()
    nodes = node_by_id(graph)
    for edge in graph_edges_for_target(graph, target_id):
        for endpoint in (edge.get("source"), edge.get("target")):
            node = nodes.get(str(endpoint))
            if not node or node.get("type") != "evidence":
                continue
            metadata = node.get("metadata") or {}
            refs.add(str(metadata.get("ref") or node.get("id") or ""))
    return sorted(ref for ref in refs if ref)


def scanner_blocker_ref(blocker: Any, *, row_id: str = "") -> str:
    if isinstance(blocker, dict):
        ref = str(
            blocker.get("mapping_id")
            or blocker.get("id")
            or blocker.get("tool")
            or blocker.get("source_locator")
            or blocker
        )
    else:
        ref = str(blocker)
    return f"{row_id}:{ref}" if row_id and ref else ref


def direct_scanner_blockers_for_node(graph: dict[str, Any], target_id: str) -> list[str]:
    node = node_by_id(graph).get(target_id) or {}
    blockers = []
    for blocker in node_value(node, "scanner_blockers", []) or []:
        blockers.append(scanner_blocker_ref(blocker))
    return sorted(set(blocker for blocker in blockers if blocker))


def compliance_rows_for_fr(graph: dict[str, Any], fr_node_id: str) -> list[str]:
    nodes = node_by_id(graph)
    rows: set[str] = set()
    for edge in graph.get("edges") or []:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if target != fr_node_id:
            continue
        source_node = nodes.get(source) or {}
        if source_node.get("type") in {"compliance", "ruleset_row"}:
            rows.add(source)
    return sorted(rows)


def scanner_blockers_for_target(graph: dict[str, Any], target_id: str, claim_type: str = "") -> list[str]:
    blockers = direct_scanner_blockers_for_node(graph, target_id)
    if claim_type in {"fr_satisfied", "no_blocking_scanner_evidence"} and target_id.startswith("fr:"):
        for row_id in compliance_rows_for_fr(graph, target_id):
            node = node_by_id(graph).get(row_id) or {}
            for blocker in node_value(node, "scanner_blockers", []) or []:
                blockers.append(scanner_blocker_ref(blocker, row_id=row_id))
    return sorted(set(blocker for blocker in blockers if blocker))


def scanner_blocker_reasons(blockers: list[str]) -> list[str]:
    if not blockers:
        return []
    return [
        "Direct scanner blockers are recorded for this claim target.",
        *[f"scanner blocker: {blocker}" for blocker in blockers[:10]],
    ]


def selected_scope_scanner_blockers(graph: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for node in graph.get("nodes") or []:
        if node.get("type") not in {"compliance", "ruleset_row"}:
            continue
        row_id = str(node.get("id") or "")
        for blocker in node_value(node, "scanner_blockers", []) or []:
            blockers.append(scanner_blocker_ref(blocker, row_id=row_id))
    return sorted(set(blockers))


def scanner_blockers_for_node_metadata(graph: dict[str, Any], target_id: str) -> list[str]:
    node = node_by_id(graph).get(target_id) or {}
    blockers = []
    for blocker in node_value(node, "scanner_blockers", []) or []:
        if isinstance(blocker, dict):
            blockers.append(str(blocker.get("mapping_id") or blocker.get("tool") or blocker))
        else:
            blockers.append(str(blocker))
    return sorted(set(blockers))


def evaluate_claim(graph: dict[str, Any], claim_type: str, target: str) -> dict[str, Any]:
    if claim_type == "selected_scope_satisfied":
        blockers = selected_scope_scanner_blockers(graph)
        failing = [
            node for node in graph.get("nodes") or []
            if node.get("type") in {"fr", "compliance", "ruleset_row"} and (
                node_value(node, "evidence_status") in UNSATISFIED_STATUSES
                or node_value(node, "status") in UNSATISFIED_STATUSES
            )
        ]
        reasons = ["Selected scope has no unsatisfied FR/compliance-row nodes or scanner blockers."]
        if failing or blockers:
            reasons = []
            if failing:
                reasons.extend([
                    f"{len(failing)} FR/compliance-row nodes are not satisfied.",
                    *[f"{node.get('id')}: {node_value(node, 'status', 'unknown')}" for node in failing[:10]],
                ])
            if blockers:
                reasons.extend(scanner_blocker_reasons(blockers))
        return {
            "target_node_id": target,
            "target_status": "satisfied" if not failing and not blockers else "unsatisfied",
            "satisfied": not failing and not blockers,
            "reasons": reasons,
            "evidence_refs": [],
            "scanner_blockers": blockers,
        }

    target_node = find_target_node(graph, claim_type, target)
    if not target_node:
        return {
            "target_node_id": "",
            "target_status": "missing",
            "satisfied": False,
            "reasons": [f"Target {target} was not found in the runtime graph."],
            "evidence_refs": [],
            "scanner_blockers": [],
        }

    target_id = str(target_node.get("id") or "")
    target_node.get("metadata") or {}
    status = str(node_value(target_node, "evidence_status") or node_value(target_node, "status") or "")
    blockers = scanner_blockers_for_target(graph, target_id, claim_type)
    reasons = [str(reason) for reason in node_value(target_node, "reasons", []) or [] if str(reason).strip()]

    if claim_type == "no_blocking_scanner_evidence":
        satisfied = not blockers and status != "failed"
        if not reasons:
            reasons = ["No blocking scanner evidence is recorded for the target."] if satisfied else ["Blocking scanner evidence is recorded for the target."]
        elif blockers:
            reasons.extend(scanner_blocker_reasons(blockers))
    else:
        satisfied = status in SATISFIED_STATUSES and not blockers
        if not reasons:
            reasons = [f"Target {target_id} has status {status or 'unknown'}."]
        if blockers:
            reasons.extend(scanner_blocker_reasons(blockers))

    return {
        "target_node_id": target_id,
        "target_status": status or "unknown",
        "satisfied": satisfied,
        "reasons": reasons,
        "evidence_refs": evidence_refs_for_target(graph, target_id),
        "scanner_blockers": blockers,
    }


def unsupported_claim_message(manifest: dict[str, Any], claim_type: str) -> str:
    unsupported = {
        item.get("claim"): item.get("missing_config_roles") or []
        for item in (manifest.get("claim_readiness") or {}).get("unsupported") or []
    }
    missing = ", ".join(unsupported.get(claim_type) or ["unknown"])
    return f"unsupported claim type for this report: {claim_type} (missing config roles: {missing})"


def assert_claim_supported(manifest: dict[str, Any], claim_type: str) -> None:
    supported = set(manifest.get("supported_claims") or [])
    if claim_type not in supported:
        raise ValueError(unsupported_claim_message(manifest, claim_type))


def build_claim(report_dir: Path, claim_type: str, target: str) -> dict[str, Any]:
    manifest_path = report_dir / "graph-manifest.json"
    payload_path = report_dir / "dashboard-payload.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"graph manifest not found: {manifest_path}")
    if not payload_path.exists():
        raise FileNotFoundError(f"dashboard payload not found: {payload_path}")

    manifest = load_json(manifest_path)
    assert_claim_supported(manifest, claim_type)
    payload = load_json(payload_path)
    evaluation = evaluate_claim(payload.get("graph") or {}, claim_type, target)
    return {
        "schema_version": 1,
        "mode": "assurance_claim",
        "claim_type": claim_type,
        "target": target,
        "claim_result": "satisfied" if evaluation["satisfied"] else "unsatisfied",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "project": str(manifest.get("project") or payload.get("project") or ""),
        "run_id": str(manifest.get("run_id") or (payload.get("summary") or {}).get("run_id") or ""),
        "graph_manifest": {
            "path": "graph-manifest.json",
            "sha256": file_sha256(manifest_path, prefixed=True),
            "graph_root_hash": manifest["commitments"]["graph_root_hash"],
            "accepted_config_hash": manifest["commitments"]["accepted_config_hash"],
        },
        "public_inputs": manifest.get("commitments") or {},
        "evaluation": evaluation,
    }


def default_output_path(report_dir: Path, claim_type: str, target: str) -> Path:
    safe_target = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in target)
    return report_dir / "claims" / f"{claim_type}.{safe_target}.json"
