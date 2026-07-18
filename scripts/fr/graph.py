#!/usr/bin/env python3
"""Graph data builder for D3 traceability graph."""
from __future__ import annotations

import json
import re
import hashlib
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from graph_vocabulary import (
    graph_edge_responsibility,
    normalise_graph_edge_type,
    normalise_graph_node_type,
)


RULESET_SNAPSHOTS = {
    "ASVS": "rulesets/asvs/5.0.0.json",
    "ISO-27001": "rulesets/iso-27001/2022.json",
    "NIST-800-53": "rulesets/nist-800-53/5.2.0.json",
    "OWASP-TOP-10": "rulesets/owasp-top-10/2021.json",
}

BEHAVIOURAL_TEST_TYPES = {"unit", "integration", "e2e", "load", "test"}

def _framework_requirements(framework: str) -> list[dict]:
    rel_path = RULESET_SNAPSHOTS.get(framework)
    if not rel_path:
        return []
    path = Path(__file__).resolve().parent.parent.parent / "data" / rel_path
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    return data.get("rows") or []


def _ruleset_row_by_id(ruleset: str, row_id: str) -> dict:
    for row in _framework_requirements(ruleset):
        if row.get("id") == row_id:
            return row
    return {}


def _scope_includes_row(row: dict, scope_entry: dict) -> bool:
    row_id = row.get("id")
    include_rows = set(scope_entry.get("include_rows") or [])
    exclude_rows = set(scope_entry.get("exclude_rows") or [])
    if row_id in exclude_rows:
        return False
    if include_rows and row_id not in include_rows:
        return False

    levels = (
        scope_entry.get("levels")
        or scope_entry.get("baselines")
        or scope_entry.get("saq")
        or scope_entry.get("tier")
    )
    if not levels:
        return True
    row_level = row.get("level")
    if row_level is None:
        return True
    levels_norm: set[str] = set()
    for level in levels:
        value = str(level).upper()
        stripped = value.lstrip("L")
        levels_norm.update({value, stripped, f"L{stripped}"})
    row_value = str(row_level).upper()
    row_stripped = row_value.lstrip("L")
    return row_value in levels_norm or row_stripped in levels_norm or f"L{row_stripped}" in levels_norm


def _chapter_for_row(row_id: str) -> str:
    value = str(row_id or "")
    match = re.match(r"^v\d+(?:\.\d+)*-(\d+)\.", value, re.I)
    if match:
        return f"V{match.group(1)}"
    match = re.match(r"^(V\d+)\.", value, re.I)
    if match:
        return match.group(1).upper()
    match = re.match(r"^([A-Z]{2,})(?:[-.].*)?$", value, re.I)
    if match and not value.lower().startswith("v"):
        return match.group(1).upper()
    return value.split(".", 1)[0] if "." in value else value.split("-", 1)[0]


def _infer_test_type_for_text(*parts: str) -> str:
    text = " ".join(parts).lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    if any(term in text for term in ("tls", "https", "proxy", "caddy", "reverse proxy")):
        return "integration"
    if any(term in words for term in ("session", "auth", "authentication", "authorization", "role", "permission", "tenant", "lockout", "mfa")):
        return "integration"
    if any(term in text for term in ("capacity", "availability", "performance", "denial of service")):
        return "load"
    if any(term in text for term in ("workflow", "lifecycle", "supersession", "ingestion", "upload", "export", "download")):
        return "e2e"
    if any(term in text for term in ("audit", "logging", "metadata", "validation", "version")):
        return "integration"
    return "unit"


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(errors="replace"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _default_scanner_compliance_packs(scope: dict | None) -> list[dict]:
    """Load file-specific scanner→compliance mapping packs for scoped regimes."""
    scope = scope or {}
    root = Path(__file__).resolve().parent.parent.parent / "data" / "scanner-mappings"
    packs: list[dict] = []
    for ruleset, scope_entry in scope.items():
        version = str((scope_entry or {}).get("version") or "")
        candidates: list[Path] = []
        ruleset_dir = root / str(ruleset).lower()
        if version:
            candidates.extend(sorted((ruleset_dir / version).glob("*.json")))
        else:
            candidates.extend(sorted(ruleset_dir.glob("*/*.json")))
        for path in candidates:
            data = _load_json(path)
            if data.get("schema_version") == 1 and data.get("mappings"):
                packs.append(data)
    return packs


def _scanner_evidence_strength(assurance_effect: str) -> str:
    if assurance_effect == "blocking_if_finding":
        return "strong"
    if assurance_effect == "review_signal":
        return "weak"
    return "supporting"


def _scanner_finding_field(finding: dict, output_field: str) -> str:
    if output_field in finding:
        return str(finding.get(output_field) or "")
    folded = {str(key).lower(): value for key, value in finding.items()}
    return str(folded.get(output_field.lower()) or "")


def _selector_matches_finding(selector: dict, finding: dict) -> bool:
    value = str(selector.get("value") or "")
    actual = _scanner_finding_field(finding, str(selector.get("output_field") or "rule_id"))
    if not value or not actual:
        return False
    selector_type = selector.get("type")
    actual_folded = actual.lower()
    value_folded = value.lower()
    if selector_type == "exact":
        return actual_folded == value_folded
    if selector_type == "prefix":
        return actual_folded.startswith(value_folded)
    if selector_type == "glob":
        return fnmatchcase(actual_folded, value_folded)
    if selector_type in {"category", "cve"}:
        return value_folded in actual_folded
    return False


def _findings_for_mapping(scanner: str, mapping: dict, scanner_findings: list[dict]) -> list[dict]:
    selectors = mapping.get("rule_selectors") or []
    findings = [finding for finding in scanner_findings if finding.get("scanner") == scanner]
    return [
        finding for finding in findings
        if any(_selector_matches_finding(selector, finding) for selector in selectors)
    ]


def _finding_key(finding: dict) -> tuple[str, str, str, str]:
    return (
        str(finding.get("scanner") or ""),
        str(finding.get("rule_id") or finding.get("id") or ""),
        str(finding.get("location") or ""),
        str(finding.get("message") or ""),
    )


def _mapped_finding_keys(packs: list[dict], scanner_findings: list[dict]) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for pack in packs:
        scanner = str(pack.get("scanner") or "")
        for mapping in pack.get("mappings") or []:
            if mapping.get("review_status") != "accepted" or mapping.get("mapping_level") == "general_finding":
                continue
            for finding in _findings_for_mapping(scanner, mapping, scanner_findings):
                keys.add(_finding_key(finding))
    return keys


def _scanner_status_for_mapping(scanner: str, health: dict, matched_findings: list[dict]) -> str:
    status = str((health.get(scanner) or {}).get("status") or "").upper()
    if matched_findings:
        return "failed"
    if status == "SKIPPED" or not status:
        return "missing"
    if status == "FAIL" or status == "WARN":
        return "partial"
    if status == "PASS":
        return "partial"
    return "manual_review"


def _scanner_compliance_index(packs: list[dict], scanner_health: dict, scanner_findings: list[dict]) -> dict[tuple[str, str], list[dict]]:
    by_row: dict[tuple[str, str], list[dict]] = {}
    for pack in packs:
        scanner = str(pack.get("scanner") or "")
        compliance = pack.get("compliance") or {}
        for mapping in pack.get("mappings") or []:
            if mapping.get("review_status") != "accepted":
                continue
            if mapping.get("mapping_level") != "compliance_row":
                continue
            matched_findings = _findings_for_mapping(scanner, mapping, scanner_findings)
            status = _scanner_status_for_mapping(scanner, scanner_health, matched_findings)
            assurance_effect = mapping.get("assurance_effect", "supporting_signal")
            signal = {
                "scanner": scanner,
                "mapping_id": mapping.get("id", ""),
                "mapping_label": mapping.get("id", ""),
                "status": status,
                "mapping_level": mapping.get("mapping_level", ""),
                "traceability_strength": mapping.get("traceability_strength", ""),
                "assurance_effect": assurance_effect,
                "evidence_role": assurance_effect,
                "evidence_strength": _scanner_evidence_strength(assurance_effect),
                "confidence": mapping.get("confidence", ""),
                "ruleset": compliance.get("ruleset", ""),
                "ruleset_version": compliance.get("version", ""),
                "rule_selectors": mapping.get("rule_selectors") or [],
                "matched_findings": matched_findings[:5],
                "matched_finding_count": len(matched_findings),
                "limitations": mapping.get("limitations") or [],
                "rationale": mapping.get("rationale", ""),
                "review_notes": mapping.get("review_notes", ""),
                "scanner_health": (scanner_health.get(scanner) or {}).get("status", ""),
                "scanner_reason": (scanner_health.get(scanner) or {}).get("reason", ""),
            }
            for row in (mapping.get("targets") or {}).get("compliance_rows") or []:
                key = (row.get("ruleset", ""), row.get("row", ""))
                if all(key):
                    by_row.setdefault(key, []).append(signal)
    return by_row


def _scanner_domain_signals(packs: list[dict], scanner_health: dict, scanner_findings: list[dict]) -> list[dict]:
    signals: list[dict] = []
    for pack in packs:
        scanner = str(pack.get("scanner") or "")
        compliance = pack.get("compliance") or {}
        for mapping in pack.get("mappings") or []:
            if mapping.get("review_status") != "accepted" or mapping.get("mapping_level") != "compliance_domain":
                continue
            matched_findings = _findings_for_mapping(scanner, mapping, scanner_findings)
            if not matched_findings:
                continue
            assurance_effect = mapping.get("assurance_effect", "review_signal")
            for domain in (mapping.get("targets") or {}).get("compliance_domains") or []:
                signals.append({
                    "scanner": scanner,
                    "mapping_id": mapping.get("id", ""),
                    "status": "manual_review",
                    "mapping_level": mapping.get("mapping_level", ""),
                    "traceability_strength": mapping.get("traceability_strength", ""),
                    "assurance_effect": assurance_effect,
                    "evidence_role": assurance_effect,
                    "evidence_strength": _scanner_evidence_strength(assurance_effect),
                    "confidence": mapping.get("confidence", ""),
                    "ruleset": domain.get("ruleset") or compliance.get("ruleset", ""),
                    "domain": domain.get("domain", ""),
                    "domain_label": domain.get("label", ""),
                    "rule_selectors": mapping.get("rule_selectors") or [],
                    "matched_findings": matched_findings[:5],
                    "matched_finding_count": len(matched_findings),
                    "limitations": mapping.get("limitations") or [],
                    "rationale": mapping.get("rationale", ""),
                    "review_notes": mapping.get("review_notes", ""),
                    "scanner_health": (scanner_health.get(scanner) or {}).get("status", ""),
                    "scanner_reason": (scanner_health.get(scanner) or {}).get("reason", ""),
                })
    return signals


def build_graph_data(
    catalog: Any | None,
    fr_evidence: dict[str, tuple[str, list[dict]]] | None = None,
    assurance_framework: Any | None = None,
    assurance_instance: dict | None = None,
    test_inventory: dict | None = None,
    assurance_pack: dict | None = None,
    evidence_bundle: dict | None = None,
    assurance_status: dict | None = None,
    scanner_health: dict | None = None,
    findings_summary: dict | None = None,
    scanner_findings: list[dict] | None = None,
    scanner_compliance_packs: list[dict] | None = None,
    graph_manifest: dict | None = None,
) -> dict:
    """Build nodes + edges for the D3 graph from FR and assurance framework catalogs.

    Structural view: compliance row → FR → required test/evidence → result.
    Missing mappings and missing proof are represented as ghost nodes so the
    dashboard can show both what exists and what is still needed.
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    fr_evidence = fr_evidence or {}
    test_inventory = test_inventory or {}
    assurance_pack = assurance_pack or {}
    evidence_bundle = evidence_bundle or {}
    assurance_status = assurance_status or {}
    scanner_health = scanner_health or {}
    findings_summary = findings_summary or {}
    scanner_findings = scanner_findings or []
    assurance_instance = assurance_instance or {}
    graph_manifest = graph_manifest or {}
    if scanner_compliance_packs is None:
        scanner_compliance_packs = _default_scanner_compliance_packs(getattr(catalog, "scope", {}) if catalog else {})
    scanner_signals_by_row = _scanner_compliance_index(scanner_compliance_packs, scanner_health, scanner_findings)
    scanner_domain_signals = _scanner_domain_signals(scanner_compliance_packs, scanner_health, scanner_findings)
    mapped_scanner_finding_keys = _mapped_finding_keys(scanner_compliance_packs, scanner_findings)
    resolved_tbt_by_id = {
        item.get("id"): item
        for item in assurance_status.get("tbts", []) or []
        if item.get("id")
    }
    resolved_fr_by_id = {
        item.get("id"): item
        for item in assurance_status.get("frs", []) or []
        if item.get("id")
    }
    resolved_row_by_id = {
        item.get("id"): item
        for item in assurance_status.get("compliance_rows", []) or []
        if item.get("id")
    }
    evidence_by_tbt: dict[str, list[dict]] = {}
    for ev in evidence_bundle.get("evidence") or []:
        produced_by = ev.get("produced_by")
        if produced_by:
            evidence_by_tbt.setdefault(produced_by, []).append(ev)
    criterion_instance_mappings = {
        mapping.get("criterion"): mapping.get("requirements") or []
        for mapping in assurance_instance.get("criterion_mappings") or []
        if mapping.get("criterion")
    }
    resolved_rows_by_fr: dict[str, list[dict]] = {}
    resolved_rows_by_tbt: dict[str, list[dict]] = {}
    for row in resolved_row_by_id.values():
        for fr_ref in row.get("fr_refs") or []:
            resolved_rows_by_fr.setdefault(fr_ref, []).append(row)
        for tbt_ref in row.get("tbt_refs") or []:
            resolved_rows_by_tbt.setdefault(tbt_ref, []).append(row)
    controls_by_target: dict[str, list[dict]] = {}
    decisions_by_target: dict[str, list[dict]] = {}
    for kind, records, default_effect in (
        ("waiver", assurance_instance.get("waivers") or [], "waived"),
        ("compensating_control", assurance_instance.get("compensating_controls") or [], "compensating_control"),
    ):
        for record in records:
            target_ref = record.get("target_ref") or {}
            target_type = target_ref.get("type", "")
            ref = target_ref.get("ref", "") or record.get("target", "")
            if target_type == "ruleset_row":
                ruleset = target_ref.get("ruleset", "")
                row = target_ref.get("row") or ref
                key = f"row:{ruleset}:{row}" if ruleset and row else ""
            elif target_type in {"fr", "tbt", "criterion", "gate"}:
                key = f"{target_type}:{ref}"
            elif ref.startswith("FR-"):
                key = f"fr:{ref}"
            elif ref.startswith("TBT-"):
                key = f"tbt:{ref}"
            elif ref.startswith("GATE-"):
                key = f"gate:{ref}"
            elif ref.startswith("CRIT-") or ref.startswith("G"):
                key = f"criterion:{ref}"
            else:
                key = ""
            if not key:
                continue
            controls_by_target.setdefault(key, []).append({
                "id": record.get("id", ""),
                "kind": kind,
                "status_effect": record.get("status_effect") or default_effect,
                "approval_status": record.get("approval_status", "pending"),
                "reason": record.get("reason", ""),
            })
    for decision in assurance_instance.get("decisions") or []:
        if decision.get("criterion"):
            key = f"criterion:{decision.get('criterion')}"
        else:
            key = f"gate:{decision.get('gate', '')}"
        if key.endswith(":"):
            continue
        decisions_by_target.setdefault(key, []).append({
            "id": decision.get("id", ""),
            "readiness_status": decision.get("readiness_status", ""),
            "outcome": decision.get("outcome", ""),
            "decision_ref": decision.get("decision_ref", ""),
        })
    gate_node_by_ref: dict[str, str] = {}
    criterion_node_by_ref: dict[str, str] = {}
    role_node_by_ref: dict[str, str] = {}

    def status_rank(status: str) -> int:
        return {"failed": 0, "execution_error": 1, "missing": 1, "blocked": 1, "manual_review": 2, "partial": 2, "waived": 2, "compensating_control": 2, "passed": 3, "satisfied": 3, "met": 3}.get(status, 2)

    def approved_control_effect(effects: list[dict]) -> dict | None:
        approved = [
            effect for effect in effects
            if effect.get("approval_status") in {"approved", "waived"}
        ]
        if not approved:
            return None
        approved.sort(key=lambda effect: 0 if effect.get("status_effect") == "compensating_control" else 1)
        return approved[0]

    def readiness_status_to_graph_status(readiness_status: str) -> str:
        return {
            "ready": "passed",
            "blocked": "failed",
            "partial": "partial",
            "manual_review": "manual_review",
            "waived": "waived",
        }.get(readiness_status, "manual_review")

    def scanner_blockers_for_rows(rows: list[dict]) -> list[dict]:
        blockers: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            for blocker in row.get("scanner_blockers") or []:
                key = (
                    str(blocker.get("tool", "")),
                    str(blocker.get("mapping_id", "")),
                    str(blocker.get("source_locator", "")),
                )
                if key in seen:
                    continue
                seen.add(key)
                enriched = dict(blocker)
                enriched.setdefault("compliance_row", row.get("id", ""))
                blockers.append(enriched)
        return blockers

    def requirement_resolution(requirement: dict) -> dict:
        rtype = requirement.get("type", "")
        ref = requirement.get("ref", "")
        if rtype == "fr" and ref:
            control = approved_control_effect(controls_by_target.get(f"fr:{ref}", []))
            if control:
                return {"status": control.get("status_effect", "manual_review"), "scanner_blockers": []}
            record = resolved_fr_by_id.get(ref, {})
            rows = resolved_rows_by_fr.get(ref, [])
            blockers = scanner_blockers_for_rows(rows)
            if record.get("status") in {"waived", "compensating_control"}:
                blockers = []
            return {
                "status": "failed" if blockers else record.get("status", "missing"),
                "scanner_blockers": blockers,
            }
        if rtype == "tbt" and ref:
            control = approved_control_effect(controls_by_target.get(f"tbt:{ref}", []))
            if control:
                return {"status": control.get("status_effect", "manual_review"), "scanner_blockers": []}
            record = resolved_tbt_by_id.get(ref, {})
            rows = resolved_rows_by_tbt.get(ref, [])
            blockers = scanner_blockers_for_rows(rows)
            if record.get("status") in {"waived", "compensating_control"}:
                blockers = []
            return {
                "status": "failed" if blockers else record.get("status", "missing"),
                "scanner_blockers": blockers,
            }
        if rtype == "ruleset_row":
            ruleset = requirement.get("ruleset", "")
            row = requirement.get("row") or ref
            control = approved_control_effect(controls_by_target.get(f"row:{ruleset}:{row}", []))
            if control:
                return {"status": control.get("status_effect", "manual_review"), "scanner_blockers": []}
            record = resolved_row_by_id.get(f"{ruleset}:{row}", {})
            blockers = scanner_blockers_for_rows([record] if record else [])
            if record.get("status") in {"waived", "compensating_control"}:
                blockers = []
            return {
                "status": "failed" if blockers else record.get("status", "missing"),
                "scanner_blockers": blockers,
            }
        if rtype in {"approval", "manual_artifact", "evidence", "waiver", "compensating_control", "decision"}:
            return {"status": "manual_review", "scanner_blockers": []}
        return {"status": "manual_review", "scanner_blockers": []}

    def criterion_resolution(criterion: dict, mapped_requirements: list[dict]) -> dict:
        criterion_key = f"criterion:{criterion.get('id', '')}"
        decision = (decisions_by_target.get(criterion_key) or [])[-1] if decisions_by_target.get(criterion_key) else None
        if decision and decision.get("readiness_status"):
            return {
                "status": readiness_status_to_graph_status(decision.get("readiness_status", "")),
                "scanner_blockers": [],
                "decision": decision,
            }
        control = approved_control_effect(controls_by_target.get(criterion_key, []))
        if control:
            return {
                "status": control.get("status_effect", "manual_review"),
                "scanner_blockers": [],
                "assurance_control": control,
            }
        requirements = list(criterion.get("requirements") or []) + list(mapped_requirements or [])
        required = [req for req in requirements if req.get("required", True)]
        if not required:
            return {"status": "manual_review", "scanner_blockers": []}
        resolutions = [requirement_resolution(req) for req in required]
        blockers = [
            blocker
            for resolution in resolutions
            for blocker in resolution.get("scanner_blockers", [])
        ]
        if blockers:
            return {"status": "failed", "scanner_blockers": blockers}
        lowest = min((status_rank(str(item.get("status", ""))) for item in resolutions), default=2)
        if lowest <= 1:
            status = "missing"
        elif lowest == 2:
            status = "manual_review"
        else:
            status = "passed"
        return {"status": status, "scanner_blockers": blockers}

    def tbt_status(tbt: dict, fallback_status: str) -> str:
        records = evidence_by_tbt.get(tbt.get("id", "")) or []
        statuses = {
            "missing" if ev.get("observed") is False or ev.get("result_status") == "not_observed"
            else ev.get("result_status", "missing")
            for ev in records
        }
        if "failed" in statuses:
            return "failed"
        if "execution_error" in statuses:
            return "execution_error"
        if "passed" in statuses:
            return "passed"
        if "partial" in statuses:
            return "partial"
        if statuses & {"manual_review", "waived"}:
            return "partial"
        if records:
            return "missing"
        return fallback_status

    def add_evidence_nodes_for_tbt(tbt_node_id: str, tbt: dict, fallback_status: str, fallback_failing: list[dict]) -> None:
        tbt_id = tbt.get("id", "")
        records = evidence_by_tbt.get(tbt_id) or []
        if records:
            for ev in records:
                ev_ref = ev.get("id") or tbt_id
                locator = ev.get("source_locator") or ev.get("source") or ""
                label = f"{ev_ref} · {locator}" if locator else ev_ref
                ev_id = f"evidence:{ev_ref}"
                add_node(
                    ev_id,
                    "evidence",
                    label,
                    evidence_type=ev.get("type", "result"),
                    status=ev.get("result_status", "missing"),
                    observed=ev.get("observed", True),
                    evidence_strength=ev.get("evidence_strength", ""),
                    ref=ev_ref,
                    source=ev.get("source", ""),
                    source_locator=ev.get("source_locator", ""),
                    source_excerpt=ev.get("source_excerpt", ""),
                    reviewer=ev.get("reviewer", ""),
                    tool=ev.get("tool", ""),
                    run_id=ev.get("run_id", ""),
                    inputs=ev.get("inputs") or (ev.get("provenance") or {}).get("input_artifacts") or [],
                    outputs=ev.get("outputs") or (ev.get("provenance") or {}).get("output_artifacts") or ev.get("raw_artifacts") or [],
                    side_effects=ev.get("side_effects") or [],
                    test_actions=ev.get("test_actions") or [],
                )
                add_edge(tbt_node_id, ev_id, "evidenced_by")
            return

        if fallback_status == "failed":
            for idx, culprit in enumerate(fallback_failing[:3]):
                culprit_ref = culprit.get("rule_id") or tbt.get("ref") or str(idx + 1)
                ev_id = f"evidence:failed:{tbt_id}:{idx}:{culprit_ref}"
                add_node(
                    ev_id,
                    "evidence",
                    culprit.get("message") or f"Failing evidence for {tbt_id}",
                    evidence_type="result",
                    status="failed",
                    ref=culprit_ref,
                    location=culprit.get("location", ""),
                    scanner=culprit.get("scanner", tbt.get("type", "")),
                )
                add_edge(tbt_node_id, ev_id, "evidenced_by")
            return

        discovered = inventory_match(tbt.get("ref") or tbt_id)
        ev_id = f"ghost:evidence:{tbt_id}"
        add_node(
            ev_id,
            "evidence",
            f"Test discovered but no passing result for {tbt_id}" if discovered else f"No passing evidence found for {tbt_id}",
            evidence_type="result",
            status="missing",
            ghost=True,
            ref=tbt.get("ref") or tbt_id,
            tbt=tbt_id,
            discovered_path=(discovered or {}).get("path", ""),
        )
        add_edge(tbt_node_id, ev_id, "evidenced_by")

    inventory_refs: dict[str, dict] = {}
    for item in test_inventory.get("files", []) or []:
        path = item.get("path", "")
        if not path:
            continue
        inventory_refs[path] = item
        inventory_refs[Path(path).name] = item
        for case in item.get("cases", []) or []:
            ref = case.get("ref", "")
            name = case.get("name", "")
            if ref:
                inventory_refs[ref] = {**item, "case": case}
            if name:
                inventory_refs[name] = {**item, "case": case}

    def inventory_match(ref: str) -> dict | None:
        if ref in inventory_refs:
            return inventory_refs[ref]
        if "::" in ref:
            path, _, name = ref.partition("::")
            for key in (path, Path(path).name, name):
                if key in inventory_refs:
                    return inventory_refs[key]
        return None

    def add_node(node_id: str, node_type: str, label: str, **extra) -> dict:
        node_type = normalise_graph_node_type(node_type)
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "type": node_type, "label": label, **extra}
        else:
            current = nodes[node_id]
            for key, value in extra.items():
                if value in (None, ""):
                    continue
                if key not in current or current.get(key) in (None, "", "unaddressed"):
                    current[key] = value
                elif current.get("type") == "compliance" and key in ("status", "na", "reason"):
                    current[key] = value
        return nodes[node_id]

    def add_edge(source: str, target: str, edge_type: str, **extra: Any) -> None:
        responsibility = graph_edge_responsibility(edge_type, extra.get("responsibility"))
        edge_type = normalise_graph_edge_type(edge_type)
        if responsibility:
            extra["responsibility"] = responsibility
        extra_key = json.dumps(extra, sort_keys=True, default=str) if extra else ""
        edge_key = f"{source}->{target}:{edge_type}:{extra_key}"
        if not any(e.get("key") == edge_key for e in edges):
            edges.append({"source": source, "target": target, "type": edge_type, "key": edge_key, **extra})

    planning_artifact_by_hash: dict[str, str] = {}

    def add_planning_artifact_nodes() -> None:
        for commitment in (graph_manifest.get("planning_artifacts", {}).get("commitments") or []):
            role = str(commitment.get("role") or "planning_artifact")
            digest = str(commitment.get("sha256") or "")
            path = str(commitment.get("path") or "")
            stable_ref = digest.removeprefix("sha256:")[:16] or re.sub(r"[^A-Za-z0-9_.-]+", "-", path)[:48]
            node_id = f"planning:{role}:{stable_ref or 'artifact'}"
            add_node(
                node_id,
                "planning_artifact",
                commitment.get("label") or role.replace("_", " "),
                role=role,
                path=path,
                sha256=digest,
                bytes=commitment.get("bytes"),
                schema=commitment.get("schema", ""),
                artifact_status=commitment.get("status", ""),
                freeze_mode=commitment.get("freeze_mode", ""),
                immutable=commitment.get("immutable"),
            )
            if digest:
                planning_artifact_by_hash[digest] = node_id
                planning_artifact_by_hash[digest.removeprefix("sha256:")] = node_id

    def add_blueprint_lineage(owner_node_id: str, derived_from: dict | None) -> None:
        if not isinstance(derived_from, dict):
            return
        source_id = str(derived_from.get("source_item") or derived_from.get("source_id") or "").strip()
        source_type = str(derived_from.get("source_type") or "").strip()
        if not source_id or not source_type.startswith("blueprint"):
            return
        node_id = f"blueprint:{source_id}"
        add_node(
            node_id,
            "blueprint",
            source_id,
            source_type=source_type,
            source_id=derived_from.get("source_id", ""),
            source_version=derived_from.get("source_version", ""),
            source_path=derived_from.get("source_path", ""),
            source_hash=derived_from.get("source_hash", ""),
            source_item=derived_from.get("source_item", ""),
            review_status=derived_from.get("review_status", ""),
            rationale=derived_from.get("rationale", ""),
            tailoring=derived_from.get("tailoring", []),
        )
        add_edge(node_id, owner_node_id, "derived_from")
        planning_node = planning_artifact_by_hash.get(str(derived_from.get("source_hash") or ""))
        if planning_node:
            add_edge(planning_node, node_id, "derived_from")

    add_planning_artifact_nodes()

    def graph_target_for_requirement(requirement: dict, *, default_required: bool = True) -> str | None:
        rtype = requirement.get("type", "")
        ref = requirement.get("ref", "")
        required = requirement.get("required", default_required)
        if rtype == "fr_placeholder":
            return None
        if rtype == "fr" and ref:
            node_id = f"fr:{ref}"
            add_node(node_id, "fr", ref, fr_id=ref, evidence_status="missing")
            return node_id
        if rtype == "tbt" and ref:
            node_id = f"test:{ref}"
            add_node(node_id, "tbt", ref, tbt=ref, status="missing")
            return node_id
        if rtype == "ruleset_row":
            ruleset = requirement.get("ruleset", "")
            row = requirement.get("row") or ref
            if not ruleset or not row:
                return None
            node_id = f"{ruleset}:{row}"
            add_node(
                node_id,
                "ruleset_row",
                f"{ruleset} {row}",
                ruleset=ruleset,
                row=row,
                chapter=_chapter_for_row(row),
                status="missing",
                required=required,
            )
            return node_id
        if rtype == "evidence" and ref:
            node_id = f"evidence:{ref}"
            add_node(node_id, "evidence", ref, evidence_type="evidence", ref=ref, status="missing", required=required)
            return node_id
        if rtype == "manual_artifact":
            evidence_ref = requirement.get("evidence") or ref
            if not evidence_ref:
                return None
            node_id = f"evidence:{evidence_ref}"
            add_node(
                node_id,
                "evidence",
                ref or evidence_ref,
                evidence_type="manual_note",
                ref=evidence_ref,
                status="manual_review",
                required=required,
            )
            return node_id
        if rtype == "approval" and ref:
            node_id = f"approval:{ref}"
            add_node(node_id, "approval", ref, ref=ref, status="pending", required=required)
            return node_id
        if rtype == "waiver" and ref:
            node_id = f"waiver:{ref}"
            add_node(node_id, "waiver", ref, ref=ref, status="pending", required=required)
            return node_id
        if rtype == "compensating_control" and ref:
            node_id = f"compensating-control:{ref}"
            add_node(node_id, "compensating_control", ref, ref=ref, status="pending", required=required)
            return node_id
        if rtype == "decision" and ref:
            node_id = f"decision:{ref}"
            add_node(node_id, "decision", ref, ref=ref, status="manual_review", required=required)
            return node_id
        return None

    def graph_target_for_instance_target(target: dict | None, fallback: str = "") -> str | None:
        target = target or {}
        target_type = target.get("type", "")
        ref = target.get("ref", "") or fallback
        if not ref:
            return None
        if target_type == "criterion":
            return criterion_node_by_ref.get(ref)
        if target_type == "gate":
            return gate_node_by_ref.get(ref)
        if target_type == "role":
            return role_node_by_ref.get(ref)
        if target_type:
            requirement = dict(target)
            requirement.setdefault("ref", ref)
            return graph_target_for_requirement(requirement, default_required=False)

        if ref.startswith("FR-"):
            return graph_target_for_requirement({"type": "fr", "ref": ref}, default_required=False)
        if ref.startswith("TBT-"):
            return graph_target_for_requirement({"type": "tbt", "ref": ref}, default_required=False)
        if ref.startswith("ROLE-"):
            return role_node_by_ref.get(ref)
        if ref.startswith("GATE-"):
            return gate_node_by_ref.get(ref)
        return None

    def add_instance_evidence_refs(source_node_id: str, evidence_refs: list[str] | None) -> None:
        for evidence_ref in evidence_refs or []:
            ev_id = f"evidence:{evidence_ref}"
            add_node(
                ev_id,
                "evidence",
                evidence_ref,
                evidence_type="manual_note",
                ref=evidence_ref,
                status="manual_review",
            )
            add_edge(source_node_id, ev_id, "evidences", mapping_source="assurance_instance")

    def add_instance_approval_ref(source_node_id: str, approval_ref: str, *, actor: str = "", signature_ref: str = "") -> None:
        if not approval_ref and not actor and not signature_ref:
            return
        ref = approval_ref or signature_ref or actor
        approval_id = f"approval:{ref}"
        add_node(
            approval_id,
            "approval",
            ref,
            ref=ref,
            status="approved" if actor or signature_ref else "pending",
            approved_by=actor,
            signature_ref=signature_ref,
        )
        add_edge(source_node_id, approval_id, "approved_by", mapping_source="assurance_instance")

    def add_assurance_instance_control_nodes() -> None:
        for waiver in assurance_instance.get("waivers") or []:
            waiver_id = waiver.get("id", "")
            if not waiver_id:
                continue
            node_id = f"waiver:{waiver_id}"
            add_node(
                node_id,
                "waiver",
                waiver_id,
                ref=waiver_id,
                status=waiver.get("approval_status", "pending"),
                status_effect=waiver.get("status_effect", "waived"),
                reason=waiver.get("reason", ""),
                scope=waiver.get("scope", ""),
                expires_at=waiver.get("expires_at", ""),
                review_due_at=waiver.get("review_due_at", ""),
                approved_by=waiver.get("approved_by", ""),
                approved_at=waiver.get("approved_at", ""),
                signature_ref=waiver.get("signature_ref", ""),
            )
            target = graph_target_for_instance_target(waiver.get("target_ref"), waiver.get("target", ""))
            if target:
                add_edge(node_id, target, "applies_to", status_effect=waiver.get("status_effect", "waived"))
            add_instance_evidence_refs(node_id, waiver.get("evidence_refs"))
            add_instance_approval_ref(
                node_id,
                waiver.get("id", ""),
                actor=waiver.get("approved_by", ""),
                signature_ref=waiver.get("signature_ref", ""),
            )

        for control in assurance_instance.get("compensating_controls") or []:
            control_id = control.get("id", "")
            if not control_id:
                continue
            node_id = f"compensating-control:{control_id}"
            add_node(
                node_id,
                "compensating_control",
                control_id,
                ref=control_id,
                status=control.get("approval_status", "pending"),
                status_effect=control.get("status_effect", "compensating_control"),
                reason=control.get("reason", ""),
                control_description=control.get("control_description", ""),
                scope=control.get("scope", ""),
                expires_at=control.get("expires_at", ""),
                review_due_at=control.get("review_due_at", ""),
                approved_by=control.get("approved_by", ""),
                approved_at=control.get("approved_at", ""),
                signature_ref=control.get("signature_ref", ""),
            )
            target = graph_target_for_instance_target(control.get("target_ref"), control.get("target", ""))
            if target:
                add_edge(
                    node_id,
                    target,
                    "applies_to",
                    status_effect=control.get("status_effect", "compensating_control"),
                )
            add_instance_evidence_refs(node_id, control.get("evidence_refs"))
            add_instance_approval_ref(
                node_id,
                control.get("id", ""),
                actor=control.get("approved_by", ""),
                signature_ref=control.get("signature_ref", ""),
            )

        for decision in assurance_instance.get("decisions") or []:
            decision_id = decision.get("id", "")
            if not decision_id:
                continue
            node_id = f"decision:{decision_id}"
            add_node(
                node_id,
                "decision",
                decision_id,
                ref=decision_id,
                status=decision.get("readiness_status", "manual_review"),
                readiness_status=decision.get("readiness_status", ""),
                outcome=decision.get("outcome", ""),
                scope=decision.get("scope", ""),
                decided_by=decision.get("decided_by", ""),
                decided_at=decision.get("decided_at", ""),
                decision_ref=decision.get("decision_ref", ""),
                signature_ref=decision.get("signature_ref", ""),
            )
            target = None
            if decision.get("criterion"):
                target = graph_target_for_instance_target({"type": "criterion", "ref": decision.get("criterion", "")})
            if not target:
                target = graph_target_for_instance_target({"type": "gate", "ref": decision.get("gate", "")})
            if target:
                add_edge(node_id, target, "applies_to", readiness_status=decision.get("readiness_status", ""))
            add_instance_evidence_refs(node_id, decision.get("evidence_refs"))
            add_instance_approval_ref(
                node_id,
                decision.get("decision_ref", ""),
                actor=decision.get("decided_by", ""),
                signature_ref=decision.get("signature_ref", ""),
            )

    canonical_frs = [
        fr for fr in (getattr(catalog, "frs", []) if catalog else [])
        if fr.get("lifecycle_status", fr.get("status", "in_scope")) == "in_scope"
    ]
    tbts_by_fr: dict[str, list[dict]] = {fr.get("id", ""): [] for fr in canonical_frs}
    for tbt in (getattr(catalog, "tbts", []) if catalog else []):
        for fr_id in tbt.get("proves") or []:
            tbts_by_fr.setdefault(fr_id, []).append(tbt)
    scoped_rows: dict[str, dict] = {}
    row_claims: dict[str, list[dict]] = {}

    def tbt_compliance_rows(tbt: dict) -> list[dict]:
        return [
            row for row in (tbt.get("compliance") or [])
            if row.get("ruleset") and row.get("row")
        ]

    def compliance_status_from_tbt_status(status: str) -> str:
        if status == "passed":
            return "satisfied"
        if status in {"partial", "manual_review", "waived", "compensating_control", "execution_error"}:
            return "partial"
        if status == "failed":
            return "failed"
        return "missing"

    def add_scanner_signal_node(row_id: str, signal: dict, *, test_node_id: str | None = None) -> None:
        scanner = signal.get("scanner", "")
        mapping_id = signal.get("mapping_id", "")
        fw = signal.get("ruleset", "")
        row = signal.get("row", "")
        ev_id = f"evidence:scanner:{scanner}:{mapping_id}:{fw}:{row}"
        label = f"{scanner} scanner signal for {fw} {row}"
        add_node(
            ev_id,
            "evidence",
            label,
            evidence_type="scanner_result",
            status=signal.get("status", "missing"),
            observed=signal.get("status") not in {"missing", "not_observed"},
            evidence_strength=signal.get("evidence_strength", "supporting"),
            evidence_role=signal.get("evidence_role", "supporting"),
            mapping_level=signal.get("mapping_level", "compliance_row"),
            traceability_strength=signal.get("traceability_strength", "direct"),
            ref=mapping_id,
            scanner=scanner,
            tool=scanner,
            ruleset=fw,
            row=row,
            run_id="scanner-run",
            source=f"reports/{scanner}.json",
            source_locator=", ".join(
                finding.get("location", "") or finding.get("rule_id", "")
                for finding in signal.get("matched_findings", [])[:3]
                if finding.get("location") or finding.get("rule_id")
            ),
            source_excerpt=signal.get("rationale", ""),
            limitations=signal.get("limitations", []),
            matched_finding_count=signal.get("matched_finding_count", 0),
            matched_findings=signal.get("matched_findings", []),
            confidence=signal.get("confidence", ""),
            scanner_health=signal.get("scanner_health", ""),
            scanner_reason=signal.get("scanner_reason", ""),
        )
        add_edge(row_id, ev_id, "evidenced_by")
        if test_node_id:
            add_edge(test_node_id, ev_id, "supported_by")

    def add_resolved_scanner_blocker_node(row_id: str, blocker: dict, *, test_node_id: str | None = None) -> None:
        scanner = blocker.get("tool") or (blocker.get("normalized_finding") or {}).get("scanner") or "scanner"
        mapping_id = blocker.get("mapping_id") or blocker.get("id") or "scanner-blocker"
        resolved_row = resolved_row_by_id.get(row_id, {})
        fw = resolved_row.get("ruleset") or row_id.split(":", 1)[0]
        row = resolved_row.get("row_id") or row_id.split(":", 1)[1] if ":" in row_id else ""
        ev_id = f"evidence:scanner-blocker:{scanner}:{mapping_id}:{fw}:{row}"
        finding = blocker.get("normalized_finding") or {}
        add_node(
            ev_id,
            "evidence",
            f"{scanner} blocker for {fw} {row}",
            evidence_type="scanner_result",
            status="failed",
            observed=True,
            evidence_strength=blocker.get("strength", "strong"),
            evidence_role=blocker.get("assurance_effect", "blocking_if_finding"),
            mapping_level="compliance_row",
            traceability_strength=blocker.get("traceability_strength", "direct"),
            ref=mapping_id,
            scanner=scanner,
            tool=scanner,
            ruleset=fw,
            row=row,
            run_id="scanner-run",
            source=blocker.get("source") or f"reports/{scanner}",
            source_locator=blocker.get("source_locator") or finding.get("location", ""),
            source_excerpt=finding.get("message", ""),
            matched_finding_count=1,
            matched_findings=[finding] if finding else [],
            confidence=blocker.get("confidence", ""),
        )
        add_edge(row_id, ev_id, "evidenced_by")
        if test_node_id:
            add_edge(test_node_id, ev_id, "supported_by")

    def add_resolved_scanner_blockers(
        row_id: str,
        *,
        test_node_id: str | None = None,
        existing_mapping_ids: set[str] | None = None,
    ) -> None:
        existing_mapping_ids = existing_mapping_ids or set()
        for blocker in (resolved_row_by_id.get(row_id) or {}).get("scanner_blockers") or []:
            if blocker.get("mapping_id") in existing_mapping_ids:
                continue
            add_resolved_scanner_blocker_node(row_id, blocker, test_node_id=test_node_id)

    for ruleset, scope_entry in ((catalog.scope or {}).items() if catalog else []):
        for row in _framework_requirements(ruleset):
            if not _scope_includes_row(row, scope_entry or {}):
                continue
            row_ref = row.get("id")
            if not row_ref:
                continue
            row_id = f"{ruleset}:{row_ref}"
            scoped_rows[row_id] = {"ruleset": ruleset, "row": row, "row_ref": row_ref}
            add_node(
                row_id,
                "compliance",
                f"{ruleset} {row_ref}",
                ruleset=ruleset,
                row=row_ref,
                chapter=row.get("chapter") or _chapter_for_row(row_ref),
                status=(resolved_row_by_id.get(row_id) or {}).get("status", "unaddressed"),
                description=row.get("description", ""),
                frs=(resolved_row_by_id.get(row_id) or {}).get("fr_refs", []),
                tbts=(resolved_row_by_id.get(row_id) or {}).get("tbt_refs", []),
                sufficiency=(resolved_row_by_id.get(row_id) or {}).get("sufficiency", {}),
                reasons=(resolved_row_by_id.get(row_id) or {}).get("reasons", []),
                scanner_blockers=(resolved_row_by_id.get(row_id) or {}).get("scanner_blockers", []),
            )
            row_signals = scanner_signals_by_row.get((ruleset, row_ref), [])
            add_resolved_scanner_blockers(
                row_id,
                existing_mapping_ids={signal.get("mapping_id", "") for signal in row_signals if signal.get("status") == "failed"},
            )
            for signal in row_signals:
                signal["ruleset"] = ruleset
                signal["row"] = row_ref
                add_scanner_signal_node(row_id, signal)

    for (ruleset, row_ref), row_signals in sorted(scanner_signals_by_row.items()):
        row_id = f"{ruleset}:{row_ref}"
        if row_id in scoped_rows:
            continue
        row = _ruleset_row_by_id(ruleset, row_ref)
        if not row:
            continue
        scoped_rows[row_id] = {"ruleset": ruleset, "row": row, "row_ref": row_ref, "source": "scanner_mapping"}
        add_node(
            row_id,
            "compliance",
            f"{ruleset} {row_ref}",
            ruleset=ruleset,
            row=row_ref,
            chapter=row.get("group") or row.get("chapter") or _chapter_for_row(row_ref),
            status=(resolved_row_by_id.get(row_id) or {}).get("status", "manual_review"),
            description=row.get("description", ""),
            frs=(resolved_row_by_id.get(row_id) or {}).get("fr_refs", []),
            tbts=(resolved_row_by_id.get(row_id) or {}).get("tbt_refs", []),
            sufficiency=(resolved_row_by_id.get(row_id) or {}).get("sufficiency", {}),
            reasons=(resolved_row_by_id.get(row_id) or {}).get("reasons", []),
            scanner_blockers=(resolved_row_by_id.get(row_id) or {}).get("scanner_blockers", []),
            traceability_strength="scanner_mapping",
        )
        add_resolved_scanner_blockers(
            row_id,
            existing_mapping_ids={signal.get("mapping_id", "") for signal in row_signals if signal.get("status") == "failed"},
        )
        for signal in row_signals:
            signal["ruleset"] = ruleset
            signal["row"] = row_ref
            add_scanner_signal_node(row_id, signal)

    for signal in scanner_domain_signals:
        ruleset = signal.get("ruleset", "")
        domain = signal.get("domain", "")
        if not ruleset or not domain:
            continue
        domain_id = f"{ruleset}:domain:{domain}"
        add_node(
            domain_id,
            "domain",
            signal.get("domain_label") or f"{ruleset} {domain}",
            ruleset=ruleset,
            domain=domain,
            status="manual_review",
            evidence_status="manual_review",
            traceability_strength="advisory",
        )
        scanner = signal.get("scanner", "")
        mapping_id = signal.get("mapping_id", "")
        ev_id = f"evidence:scanner-domain:{scanner}:{mapping_id}:{ruleset}:{domain}"
        add_node(
            ev_id,
            "evidence",
            f"{scanner} advisory scanner signal for {ruleset} {domain}",
            evidence_type="scanner_result",
            status=signal.get("status", "manual_review"),
            observed=True,
            evidence_strength=signal.get("evidence_strength", "weak"),
            evidence_role=signal.get("evidence_role", "review_signal"),
            mapping_level="compliance_domain",
            traceability_strength=signal.get("traceability_strength", "advisory"),
            ref=mapping_id,
            scanner=scanner,
            tool=scanner,
            ruleset=ruleset,
            domain=domain,
            run_id="scanner-run",
            source=f"reports/{scanner}.json",
            source_locator=", ".join(
                finding.get("location", "") or finding.get("rule_id", "")
                for finding in signal.get("matched_findings", [])[:3]
                if finding.get("location") or finding.get("rule_id")
            ),
            source_excerpt=signal.get("rationale", ""),
            limitations=signal.get("limitations", []),
            matched_finding_count=signal.get("matched_finding_count", 0),
            matched_findings=signal.get("matched_findings", []),
            confidence=signal.get("confidence", ""),
            scanner_health=signal.get("scanner_health", ""),
            scanner_reason=signal.get("scanner_reason", ""),
        )
        add_edge(domain_id, ev_id, "evidenced_by")

    scanner_inventory_roots: set[str] = set()
    for finding in scanner_findings:
        scanner = str(finding.get("scanner") or "scanner")
        scanner_root_id = f"scanner-inventory:{scanner}"
        if scanner_root_id not in scanner_inventory_roots:
            scanner_inventory_roots.add(scanner_root_id)
            add_node(
                scanner_root_id,
                "evidence",
                f"{scanner} scanner findings inventory",
                evidence_type="scanner_result",
                status="observed",
                observed=True,
                evidence_strength="inventory",
                evidence_role="scanner_inventory",
                mapping_level="scanner_inventory",
                traceability_strength="inventory",
                scanner=scanner,
                tool=scanner,
                run_id="scanner-run",
                source=f"reports/{scanner}",
            )
        finding_key = _finding_key(finding)
        finding_hash = hashlib.sha256("|".join(finding_key).encode("utf-8")).hexdigest()[:16]
        mapped = finding_key in mapped_scanner_finding_keys
        rule_id = str(finding.get("rule_id") or finding.get("id") or "scanner-finding")
        location = str(finding.get("location") or "")
        node_id = f"evidence:scanner-finding:{scanner}:{finding_hash}"
        add_node(
            node_id,
            "evidence",
            f"{scanner} {rule_id}",
            evidence_type="scanner_result",
            status="failed",
            observed=True,
            evidence_strength="inventory",
            evidence_role="scanner_finding",
            mapping_level="mapped_finding" if mapped else "general_finding",
            traceability_strength="mapped_inventory" if mapped else "unmapped",
            scanner=scanner,
            tool=scanner,
            rule_id=rule_id,
            ref=rule_id,
            run_id="scanner-run",
            source=f"reports/{scanner}",
            source_locator=location,
            source_excerpt=str(finding.get("message") or ""),
            path=str(finding.get("path") or ""),
            mapped_to_assurance=mapped,
            matched_finding_count=1,
            matched_findings=[finding],
        )
        add_edge(scanner_root_id, node_id, "maps_to")

    unmapped_by_scanner: dict[str, list[dict]] = {}
    for finding in scanner_findings:
        if _finding_key(finding) not in mapped_scanner_finding_keys:
            unmapped_by_scanner.setdefault(str(finding.get("scanner") or "scanner"), []).append(finding)
    for scanner, findings in sorted(unmapped_by_scanner.items()):
        ev_id = f"evidence:scanner-general:{scanner}"
        add_node(
            ev_id,
            "evidence",
            f"{scanner} unmapped scanner findings",
            evidence_type="scanner_result",
            status="manual_review",
            observed=True,
            evidence_strength="weak",
            evidence_role="inventory_only",
            mapping_level="general_finding",
            traceability_strength="unmapped",
            scanner=scanner,
            tool=scanner,
            run_id="scanner-run",
            source=f"reports/{scanner}.json",
            matched_finding_count=len(findings),
            matched_findings=findings[:5],
            source_locator=", ".join(
                finding.get("location", "") or finding.get("rule_id", "")
                for finding in findings[:3]
                if finding.get("location") or finding.get("rule_id")
            ),
            source_excerpt="Scanner findings with no accepted direct ASVS row or ASVS domain mapping.",
        )

    for tbt in (getattr(catalog, "tbts", []) if catalog else []):
        proving_frs = [
            fr_by_id for fr_by_id in canonical_frs
            if fr_by_id.get("id") in (tbt.get("proves") or [])
        ]
        for row in tbt_compliance_rows(tbt):
            fw = row.get("ruleset", "?")
            row_ref = row.get("row", "?")
            for req in proving_frs:
                row_claims.setdefault(f"{fw}:{row_ref}", []).append(req)

    for req in canonical_frs:
        if req.get("status") != "in_scope":
            if req.get("lifecycle_status", "in_scope") != "in_scope":
                continue
        evidence_status, failing = fr_evidence.get(req["id"], ("missing", []))
        resolved_fr = resolved_fr_by_id.get(req["id"], {})
        if resolved_fr.get("status"):
            evidence_status = resolved_fr["status"]
        fr_id = f"fr:{req['id']}"
        add_node(
            fr_id,
            "fr",
            req["title"],
            status=req.get("lifecycle_status", req.get("status", "in_scope")),
            evidence_status=evidence_status,
            failure_count=len(failing),
            fr_id=req["id"],
            category=req.get("category", "uncategorized"),
            owner=req.get("owner", ""),
            assignments=req.get("assignments", []),
            description=req.get("description", ""),
            tbts=resolved_fr.get("tbts", []),
            reasons=resolved_fr.get("reasons", []),
        )
        add_blueprint_lineage(fr_id, req.get("derived_from"))

        for assignment in req.get("assignments") or []:
            party = str(assignment.get("party") or "").strip()
            responsibility = str(assignment.get("responsibility") or "owner").strip()
            if not party:
                continue
            party_id = f"party:{party}"
            add_node(
                party_id,
                "party",
                party,
                party=party,
                responsibility=responsibility,
                assignment_source=assignment.get("source", ""),
            )
            add_edge(
                fr_id,
                party_id,
                "assigned_to",
                responsibility=responsibility,
                assignment_source=assignment.get("source", ""),
            )

        # Code references
        for impl in req.get("implemented_by") or []:
            path = impl.get("path", "?")
            label = impl.get("label") or path
            code_id = f"code:{path}"
            add_node(code_id, "code", label, path=path, ref_type=impl.get("type", "file"))
            add_edge(fr_id, code_id, "implements")

        # TBTs (test basis records) prove FRs and produce evidence.
        fr_tbts = tbts_by_fr.get(req["id"]) or []
        if fr_tbts:
            for tbt in fr_tbts:
                tbt_id = tbt.get("id", "")
                ref = tbt.get("ref") or tbt_id
                ttype = tbt.get("type", "test")
                node_type = "scanner" if ttype == "scanner" else (ttype or "test")
                node_id = f"test:{tbt_id}"
                discovered = inventory_match(ref)
                status = tbt_status(tbt, "missing" if tbt.get("lifecycle_status") == "planned" else evidence_status)
                resolved_tbt = resolved_tbt_by_id.get(tbt_id, {})
                if resolved_tbt.get("status"):
                    status = resolved_tbt["status"]
                add_node(
                    node_id,
                    node_type,
                    tbt.get("title") or tbt_id,
                    ref=ref,
                    tbt=tbt_id,
                    status=status,
                    lifecycle_status=tbt.get("lifecycle_status", ""),
                    evidence_policy=tbt.get("evidence_policy", ""),
                    runner=tbt.get("runner", ""),
                    discovered_path=(discovered or {}).get("path", ""),
                    discovered_framework=(discovered or {}).get("framework", ""),
                    expected_evidence=resolved_tbt.get("evidence_requirements", resolved_tbt.get("expected_evidence", tbt.get("expected_evidence", []))),
                    resolved_evidence=resolved_tbt.get("observed_evidence", []),
                    evidence_summary=resolved_tbt.get("evidence_summary", {}),
                    reasons=resolved_tbt.get("reasons", []),
                )
                add_blueprint_lineage(node_id, tbt.get("derived_from"))
                add_edge(fr_id, node_id, "verified_by")
                add_evidence_nodes_for_tbt(node_id, tbt, status, failing)

                for row_ref in tbt_compliance_rows(tbt):
                    fw = row_ref.get("ruleset", "?")
                    row = row_ref.get("row", "?")
                    row_id = f"{fw}:{row}"
                    label = f"{fw} {row}"
                    resolved_row = resolved_row_by_id.get(row_id, {})
                    row_status = resolved_row.get("status") or compliance_status_from_tbt_status(status)
                    chapter = _chapter_for_row(row)
                    add_node(
                        row_id,
                        "compliance",
                        label,
                        ruleset=fw,
                        row=row,
                        chapter=chapter,
                        status=row_status,
                        na=(row_status == "na"),
                        reason=row_ref.get("reason", ""),
                        frs=resolved_row.get("fr_refs", tbt.get("proves", [])),
                        tbts=resolved_row.get("tbt_refs", [tbt_id]),
                        sufficiency=resolved_row.get("sufficiency", {}),
                        reasons=resolved_row.get("reasons", []),
                        scanner_blockers=resolved_row.get("scanner_blockers", []),
                    )
                    add_edge(row_id, fr_id, "satisfies")
                    add_edge(row_id, node_id, "requires_tbt")
                    row_signals = scanner_signals_by_row.get((fw, row), [])
                    add_resolved_scanner_blockers(
                        row_id,
                        test_node_id=node_id,
                        existing_mapping_ids={signal.get("mapping_id", "") for signal in row_signals if signal.get("status") == "failed"},
                    )
                    for signal in row_signals:
                        signal["ruleset"] = fw
                        signal["row"] = row
                        add_scanner_signal_node(row_id, signal, test_node_id=node_id)

        if not fr_tbts:
            test_type = _infer_test_type_for_text(
                req.get("id", ""),
                req.get("title", ""),
                req.get("category", ""),
                req.get("description", ""),
            )
            ghost_test = f"ghost:test:{req['id']}:{test_type}"
            ghost_evidence = f"ghost:evidence:{req['id']}:{test_type}"
            add_node(
                ghost_test,
                test_type,
                f"Suggested {test_type} test for {req['id']}",
                status="missing",
                ghost=True,
                ref=req["id"],
            )
            add_node(
                ghost_evidence,
                "evidence",
                "No passing project test evidence yet",
                evidence_type="result",
                status="missing",
                ghost=True,
                ref=req["id"],
            )
            add_edge(fr_id, ghost_test, "requires_test")
            add_edge(ghost_test, ghost_evidence, "evidenced_by")

        # Evidence artifacts
        for ev in req.get("evidence") or []:
            ev_ref = ev.get("ref", "?")
            ev_type = ev.get("type", "manual")
            locator = ev.get("source_locator") or ev.get("locator") or ev.get("section") or ""
            ev_id = f"evidence:{req['id']}:{ev_ref}" if locator else f"evidence:{ev_ref}"
            label = f"{ev_ref} · {locator}" if locator else ev_ref
            add_node(
                ev_id,
                "evidence",
                label,
                evidence_type=ev_type,
                status=ev.get("status", "auto"),
                ref=ev_ref,
                source_locator=locator,
                source_excerpt=ev.get("source_excerpt", ""),
                source_lines=ev.get("source_lines", ""),
            )
            add_edge(fr_id, ev_id, "evidenced_by")

    inventory_root_id = "test-inventory:project"
    if test_inventory.get("files"):
        summary = test_inventory.get("summary") or {}
        add_node(
            inventory_root_id,
            "evidence",
            "Project test inventory",
            evidence_type="test-inventory",
            status="discovered",
            description=f"{summary.get('files', 0)} files, {summary.get('cases', 0)} cases discovered",
        )
        for item in (test_inventory.get("files") or [])[:200]:
            path = item.get("path", "")
            if not path:
                continue
            node_id = f"project-test:{path}"
            add_node(
                node_id,
                item.get("type") or "test",
                path,
                ref=path,
                status="discovered",
                framework=item.get("framework", ""),
                case_count=len(item.get("cases") or []),
            )
            add_edge(inventory_root_id, node_id, "discovers")

    if assurance_pack.get("tests"):
        pack_root_id = "assurance-pack:VG_TEST_FRAMEWORK"
        summary = assurance_pack.get("summary") or {}
        add_node(
            pack_root_id,
            "evidence",
            "VG_TEST_FRAMEWORK",
            evidence_type="assurance-test-pack",
            status=assurance_pack.get("mode", "ephemeral"),
            description=(
                f"{summary.get('copied_native', 0)} copied native tests, "
                f"{summary.get('planned_tbt', 0)} planned TBT entries"
            ),
        )
        for item in (assurance_pack.get("tests") or [])[:300]:
            tbt = item.get("tbt")
            pack_id = item.get("pack_id") or tbt or item.get("pack_path")
            if not pack_id:
                continue
            node_id = f"assurance-test:{pack_id}"
            node_type = item.get("type") or "test"
            add_node(
                node_id,
                node_type,
                item.get("title") or item.get("pack_path") or pack_id,
                ref=item.get("pack_path") or item.get("native_path", ""),
                tbt=tbt or "",
                frs=item.get("frs", []),
                status=item.get("status", ""),
                assessment=item.get("assessment", ""),
                safety=item.get("safety", ""),
                runner=item.get("runner", ""),
                source=item.get("source", ""),
                description=item.get("rationale", ""),
            )
            add_edge(pack_root_id, node_id, "contains_test")
            if tbt:
                tbt_id = f"test:{tbt}"
                add_node(tbt_id, node_type, tbt, tbt=tbt, status=item.get("status", "planned"))
                add_edge(tbt_id, node_id, "packaged_as")
            item_frs = item.get("frs") or []
            for item_fr in item_frs:
                fr_node = f"fr:{item_fr}"
                add_node(fr_node, "fr", item_fr, fr_id=item_fr, evidence_status="missing")
                if tbt:
                    tbt_id = f"test:{tbt}"
                    if not any(
                        e.get("source") == fr_node
                        and e.get("target") == tbt_id
                        and e.get("type") in {"verified_by", "requires_test"}
                        for e in edges
                    ):
                        add_edge(fr_node, tbt_id, "requires_test")
                else:
                    add_edge(fr_node, node_id, "requires_test")

    for row_id, row_info in scoped_rows.items():
        if row_claims.get(row_id):
            continue
        framework = row_info["ruleset"]
        row_ref = row_info["row_ref"]
        row = row_info["row"]
        test_type = _infer_test_type_for_text(row_ref, row.get("chapter", ""), row.get("description", ""))
        ghost_fr = f"ghost:fr:{framework}:{row_ref}"
        ghost_test = f"ghost:test:{framework}:{row_ref}:{test_type}"
        ghost_evidence = f"ghost:evidence:{framework}:{row_ref}"
        add_node(
            ghost_fr,
            "fr",
            f"Missing FR for {framework} {row_ref}",
            fr_id="Missing FR",
            evidence_status="missing",
            status="missing",
            ghost=True,
            description=row.get("description", ""),
        )
        add_node(
            ghost_test,
            test_type,
            f"Suggested {test_type} test",
            status="missing",
            ghost=True,
            ref=row_ref,
        )
        add_node(
            ghost_evidence,
            "evidence",
            "No passing evidence yet",
            evidence_type="result",
            status="missing",
            ghost=True,
            ref=row_ref,
        )
        add_edge(row_id, ghost_fr, "requires_fr")
        add_edge(ghost_fr, ghost_test, "requires_test")
        add_edge(ghost_test, ghost_evidence, "evidenced_by")

    if assurance_framework:
        for role in assurance_framework.roles:
            role_id = f"role:{role['id']}"
            add_node(
                role_id,
                "role",
                role.get("title", role["id"]),
                role_id=role["id"],
                party_type=role.get("party_type", "other"),
                description=role.get("description", ""),
            )

        for process in assurance_framework.processes:
            process_id = f"process:{process['id']}"
            add_node(
                process_id,
                "process",
                process.get("title", process["id"]),
                process_id=process["id"],
                status=process.get("status", "active"),
                description=process.get("description", ""),
            )
            for gate in process.get("gates") or []:
                gate_id = f"gate:{process['id']}:{gate['id']}"
                gate_node_by_ref[gate["id"]] = gate_id
                gate_criterion_resolutions = [
                    criterion_resolution(
                        criterion,
                        criterion_instance_mappings.get(criterion.get("id"), []),
                    )
                    for criterion in gate.get("criteria") or []
                    if criterion.get("required", True)
                ]
                gate_scanner_blockers = [
                    blocker
                    for resolution in gate_criterion_resolutions
                    for blocker in resolution.get("scanner_blockers", [])
                ]
                if gate_scanner_blockers or any(resolution.get("status") == "failed" for resolution in gate_criterion_resolutions):
                    gate_status = "failed"
                elif any(resolution.get("status") == "missing" for resolution in gate_criterion_resolutions):
                    gate_status = "missing"
                elif any(resolution.get("status") == "manual_review" for resolution in gate_criterion_resolutions):
                    gate_status = "manual_review"
                elif any(resolution.get("status") in {"partial", "waived", "compensating_control"} for resolution in gate_criterion_resolutions):
                    gate_status = "partial"
                elif gate_criterion_resolutions:
                    gate_status = "passed"
                else:
                    gate_status = "manual_review"
                gate_key = f"gate:{gate.get('id', '')}"
                gate_decision = (decisions_by_target.get(gate_key) or [])[-1] if decisions_by_target.get(gate_key) else None
                gate_control = approved_control_effect(controls_by_target.get(gate_key, []))
                if gate_decision and gate_decision.get("readiness_status"):
                    gate_status = readiness_status_to_graph_status(gate_decision.get("readiness_status", ""))
                    if gate_status != "failed":
                        gate_scanner_blockers = []
                elif gate_control:
                    gate_status = gate_control.get("status_effect", "manual_review")
                    gate_scanner_blockers = []
                add_node(
                    gate_id,
                    "gate",
                    gate.get("title", gate["id"]),
                    gate_id=gate["id"],
                    sequence=gate.get("sequence"),
                    continuation_rule=gate.get("continuation_rule", "all_mandatory_criteria_met"),
                    status=gate_status,
                    scanner_blocker_count=len(gate_scanner_blockers),
                    scanner_blockers=gate_scanner_blockers[:5],
                    assurance_control=gate_control or {},
                    decision=gate_decision or {},
                    description=gate.get("description", ""),
                )
                add_edge(process_id, gate_id, "contains_gate")

                for role_req in gate.get("required_roles") or []:
                    role_ref = role_req.get("role", "?")
                    role_node_id = f"role:{role_ref}"
                    role_node_by_ref[role_ref] = role_node_id
                    add_node(
                        role_node_id,
                        "role",
                        role_ref,
                        role_id=role_ref,
                        party=role_req.get("party", ""),
                        status=role_req.get("status", "pending"),
                    )
                    add_edge(
                        gate_id,
                        role_node_id,
                        "assigned_to",
                        responsibility=role_req.get("responsibility", "owner"),
                    )

                for criterion in gate.get("criteria") or []:
                    criterion_id = f"criterion:{process['id']}:{gate['id']}:{criterion['id']}"
                    criterion_node_by_ref[criterion["id"]] = criterion_id
                    resolution = criterion_resolution(
                        criterion,
                        criterion_instance_mappings.get(criterion.get("id"), []),
                    )
                    add_node(
                        criterion_id,
                        "criterion",
                        criterion.get("title", criterion["id"]),
                        criterion_id=criterion["id"],
                        required=criterion.get("required", True),
                        status=resolution.get("status", "manual_review"),
                        scanner_blocker_count=len(resolution.get("scanner_blockers", [])),
                        scanner_blockers=resolution.get("scanner_blockers", [])[:5],
                        assurance_control=resolution.get("assurance_control", {}),
                        decision=resolution.get("decision", {}),
                        description=criterion.get("description", ""),
                    )
                    add_edge(gate_id, criterion_id, "has_criterion")

                    for requirement in criterion.get("requirements") or []:
                        target = graph_target_for_requirement(requirement)
                        if target:
                            add_edge(
                                criterion_id,
                                target,
                                "requires",
                                mapping_source="assurance_framework",
                                requirement_type=requirement.get("type", ""),
                            )

                    for requirement in criterion_instance_mappings.get(criterion.get("id"), []):
                        target = graph_target_for_requirement(requirement)
                        if target:
                            add_edge(
                                criterion_id,
                                target,
                                "requires",
                                mapping_source="assurance_instance",
                                requirement_type=requirement.get("type", ""),
                            )

    add_assurance_instance_control_nodes()

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "meta": {
            "soft_cap": 500,
            "default_status": "failed",
        },
    }
