#!/usr/bin/env python3
"""Assurance Gates tab renderer."""
from __future__ import annotations

import html
import importlib.util
from pathlib import Path
from typing import Any


def render_assurance_framework(
    assurance_framework_path: str | None,
    *,
    report_dir: Path,
    fr_catalog: Any | None = None,
    fr_evidence: dict[str, tuple[str, list[dict]]] | None = None,
    assurance_framework: Any | None = None,
    evidence_bundle: dict[str, Any] | None = None,
    assurance_status: dict[str, Any] | None = None,
    assurance_instance: dict[str, Any] | None = None,
) -> str:
    """Render a process-gate catalog as dashboard HTML."""
    catalog = assurance_framework or _load_catalog(assurance_framework_path, fr_catalog=fr_catalog)
    if isinstance(catalog, str):
        return _assurance_framework_error(catalog)

    if not catalog.processes:
        return (
            '<section class="card"><div class="empty-state">'
            'No processes defined. Add a process with gates and rescan.'
            '</div></section>'
        )

    target_dir = _target_dir_from_manifest(report_dir)
    target_evidence = _target_evidence_indexes(evidence_bundle)
    resolved_status = _assurance_status_indexes(assurance_status)
    gate_exceptions = _gate_exception_indexes(assurance_instance)
    role_lookup = {r["id"]: r for r in catalog.roles}
    gate_states = []
    for process in catalog.processes:
        for gate in process.get("gates") or []:
            gate_states.append(_compute_gate_state(
                gate,
                role_lookup=role_lookup,
                target_dir=target_dir,
                fr_catalog=fr_catalog,
                fr_evidence=fr_evidence or {},
                target_evidence=target_evidence,
                resolved_status=resolved_status,
                gate_exceptions=gate_exceptions,
            ))

    counts = {"met": 0, "partial": 0, "blocked": 0, "manual": 0}
    for state in gate_states:
        counts[state["status"]] = counts.get(state["status"], 0) + 1

    tiles = (
        f'<div class="metric"><b>{len(catalog.processes)}</b><span>Processes</span></div>'
        f'<div class="metric"><b>{len(gate_states)}</b><span>Gates</span></div>'
        f'<div class="metric"><b>{counts.get("met", 0)}</b><span>Met</span></div>'
        f'<div class="metric"><b>{counts.get("blocked", 0)}</b><span>Blocked</span></div>'
    )

    warning_banner = ""
    warn_items = [w for w in catalog.warnings if w.severity == "warn"]
    if warn_items:
        items = "".join(
            f'<li>[{html.escape(w.severity)}] {html.escape(w.code)}: {html.escape(w.message)}</li>'
            for w in warn_items
        )
        warning_banner = (
            f'<div class="callout"><strong>{len(warn_items)} validation warning(s):</strong>'
            f'<ul>{items}</ul></div>'
        )

    role_rows = "".join(_render_role_row(role) for role in catalog.roles)
    process_blocks = []
    for process in catalog.processes:
        process_blocks.append(_render_process(process, role_lookup, target_dir, fr_catalog, fr_evidence or {}, target_evidence, resolved_status, gate_exceptions))

    return (
        f'{warning_banner}'
        f'<section class="card process-card">'
        f'<div class="card-head"><h2>{html.escape(catalog.title)}</h2>'
        f'<span class="meta">{html.escape(catalog.assurance_framework)} process gate readiness</span></div>'
        f'<div class="metric-grid" style="grid-template-columns:repeat(4,minmax(120px,1fr));margin-bottom:12px">{tiles}</div>'
        f'<div class="process-layout">'
        f'<aside class="process-role-panel"><h3>Roles</h3><table class="process-role-table"><tbody>{role_rows}</tbody></table></aside>'
        f'<div class="process-flow">{"".join(process_blocks)}</div>'
        f'</div></section>'
    )


def build_process_flow_data(
    assurance_framework_path: str | None,
    *,
    report_dir: Path,
    fr_catalog: Any | None = None,
    fr_evidence: dict[str, tuple[str, list[dict]]] | None = None,
    assurance_framework: Any | None = None,
    evidence_bundle: dict[str, Any] | None = None,
    assurance_status: dict[str, Any] | None = None,
    assurance_instance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build compact process/gate/role data for the D3 gate-flow view."""
    catalog = assurance_framework or _load_catalog(assurance_framework_path, fr_catalog=fr_catalog)
    if isinstance(catalog, str) or not catalog.processes:
        return {"assurance_framework": "", "title": "", "processes": []}

    target_dir = _target_dir_from_manifest(report_dir)
    target_evidence = _target_evidence_indexes(evidence_bundle)
    resolved_status = _assurance_status_indexes(assurance_status)
    gate_exceptions = _gate_exception_indexes(assurance_instance)
    role_lookup = {r["id"]: r for r in catalog.roles}
    profiles, selected_profile = _process_profiles(catalog)
    processes: list[dict[str, Any]] = []
    for process in catalog.processes:
        gates = []
        sorted_gates = sorted(process.get("gates") or [], key=lambda g: g.get("sequence", 0))
        for gate in sorted_gates:
            state = _compute_gate_state(
                gate,
                role_lookup=role_lookup,
                target_dir=target_dir,
                fr_catalog=fr_catalog,
                fr_evidence=fr_evidence or {},
                target_evidence=target_evidence,
                resolved_status=resolved_status,
                gate_exceptions=gate_exceptions,
            )
            roles = []
            for role_req in gate.get("required_roles") or []:
                role = role_lookup.get(role_req.get("role", ""), {})
                approved = role_req.get("status") in ("approved", "waived")
                assigned = bool(role_req.get("party") or role_req.get("approval_ref") or approved)
                roles.append({
                    "role": role_req.get("role", ""),
                    "title": role.get("title") or role_req.get("role", ""),
                    "responsibility": role_req.get("responsibility", ""),
                    "required": role_req.get("required", True),
                    "party": role_req.get("party", ""),
                    "status": role_req.get("status", ""),
                    "assigned": assigned or role_req.get("required", True) is False,
                    "profiles": _normalise_profiles(role_req.get("profiles"), profiles),
                })
            gates.append({
                "id": gate.get("id", ""),
                "title": gate.get("title", ""),
                "sequence": gate.get("sequence", 0),
                "description": gate.get("description", ""),
                "continuation_rule": gate.get("continuation_rule", "all_mandatory_criteria_met"),
                "status": state["status"],
                "met_criteria": state["met_criteria"],
                "required_criteria": state["required_criteria"],
                "blockers": state["blockers"][:6],
                "scanner_blockers": state.get("scanner_blockers", [])[:6],
                "scanner_blocker_count": state.get("scanner_blocker_count", 0),
                "roles": roles,
                "criteria": state["criteria"],
                "compliance_rules": _gate_compliance_rules(state["criteria"], fr_catalog, fr_evidence or {}),
                "profiles": _normalise_profiles(gate.get("profiles"), profiles),
            })
        processes.append({
            "id": process.get("id", ""),
            "title": process.get("title", ""),
            "description": process.get("description", ""),
            "entry_conditions": process.get("entry_conditions") or [],
            "exit_outcomes": process.get("exit_outcomes") or [],
            "transitions": process.get("transitions") or [],
            "gates": gates,
        })
    return {
        "assurance_framework": catalog.assurance_framework,
        "title": catalog.title,
        "version": catalog.version,
        "profiles": profiles,
        "selected_profile": selected_profile,
        "process_links": (getattr(catalog, "raw", {}) or {}).get("process_links") or [],
        "processes": processes,
    }


def _gate_compliance_rules(
    criteria: list[dict[str, Any]],
    fr_catalog: Any | None,
    fr_evidence: dict[str, tuple[str, list[dict]]],
) -> list[dict[str, Any]]:
    """Return compliance rows reached through FR evidence links in gate criteria."""
    if not fr_catalog:
        return []
    req_by_id = {
        req.get("id"): req
        for req in (getattr(fr_catalog, "frs", []) or [])
        if isinstance(req, dict) and req.get("id")
    }
    tbts_by_fr: dict[str, list[dict[str, Any]]] = {}
    for tbt in (getattr(fr_catalog, "tbts", []) or []):
        for fr_id in tbt.get("proves") or []:
            tbts_by_fr.setdefault(fr_id, []).append(tbt)
    rules: dict[tuple[str, str, str], dict[str, Any]] = {}
    for criterion in criteria:
        for evidence in criterion.get("evidence") or []:
            if evidence.get("type") != "fr":
                continue
            fr_id = evidence.get("ref", "")
            req = req_by_id.get(fr_id)
            if not req:
                continue
            fr_status = fr_evidence.get(fr_id, ("missing", []))[0]
            tbt_rows = [
                row
                for tbt in tbts_by_fr.get(fr_id, [])
                for row in (tbt.get("compliance") or [])
            ]
            for row in tbt_rows:
                ruleset = row.get("ruleset", "")
                row_id = row.get("row", "")
                if not ruleset or not row_id:
                    continue
                key = (ruleset, row_id, fr_id)
                current = rules.get(key)
                required = bool(evidence.get("required", True))
                if current:
                    current["criteria"].append(criterion.get("id", ""))
                    current["required"] = current["required"] or required
                    continue
                rules[key] = {
                    "ruleset": ruleset,
                    "row": row_id,
                    "fr_id": fr_id,
                    "fr_title": req.get("title", ""),
                    "fr_status": fr_status,
                    "required": required,
                    "criteria": [criterion.get("id", "")],
                    "profiles": _normalise_profiles(evidence.get("profiles") or criterion.get("profiles"), None),
                }
    return sorted(
        rules.values(),
        key=lambda r: (r["ruleset"], _natural_row_key(r["row"]), r["fr_id"]),
    )


def _natural_row_key(value: str) -> tuple[Any, ...]:
    import re
    parts = re.split(r"(\d+)", str(value))
    return tuple(int(p) if p.isdigit() else p.lower() for p in parts)


def _process_profiles(catalog: Any) -> tuple[list[dict[str, str]], str]:
    raw = getattr(catalog, "raw", {}) or {}
    profiles: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_profile(profile: dict[str, Any]) -> None:
        profile_id = _normalise_profile(profile.get("id"))
        if not profile_id or profile_id in seen:
            return
        seen.add(profile_id)
        profiles.append({
            "id": profile_id,
            "title": str(profile.get("title") or profile_id),
            "description": str(profile.get("description") or ""),
        })

    for profile in raw.get("assurance_profiles") or []:
        if isinstance(profile, dict):
            add_profile(profile)

    def add_refs(values: Any) -> None:
        for profile_id in _normalise_profiles(values, None):
            if profile_id not in seen:
                add_profile({"id": profile_id, "title": profile_id})

    for process in getattr(catalog, "processes", []) or []:
        add_refs(process.get("profiles"))
        for gate in process.get("gates") or []:
            add_refs(gate.get("profiles"))
            for role in gate.get("required_roles") or []:
                add_refs(role.get("profiles"))
            for criterion in gate.get("criteria") or []:
                add_refs(criterion.get("profiles"))
                for evidence in criterion.get("evidence") or []:
                    add_refs(evidence.get("profiles"))

    if not profiles:
        add_profile({"id": "baseline", "title": "Baseline assurance"})

    selected = _normalise_profile(raw.get("selected_profile"))
    if not selected:
        selected = profiles[0]["id"]
    if selected not in seen:
        add_profile({"id": selected, "title": selected})
    return profiles, selected


def _normalise_profile(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalise_profiles(values: Any, default: list[dict[str, str]] | list[str] | None = None) -> list[str]:
    if values is None:
        if not default:
            return []
        if default and isinstance(default[0], dict):  # type: ignore[index]
            return [str(item.get("id", "")) for item in default if item.get("id")]  # type: ignore[union-attr]
        return [str(item) for item in default]
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        profile = _normalise_profile(value)
        if profile and profile not in out:
            out.append(profile)
    return out


def _load_catalog(assurance_framework_path: str | None, *, fr_catalog: Any | None) -> Any | str:
    if not assurance_framework_path:
        return "No assurance framework path supplied."
    loader_path = Path(__file__).resolve().parent.parent / "load_assurance_framework.py"
    spec = importlib.util.spec_from_file_location("load_assurance_framework", loader_path)
    if spec is None or spec.loader is None:
        return "Could not load assurance framework loader module."
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)  # type: ignore[union-attr]

    try:
        return loader.load_assurance_framework(Path(assurance_framework_path))
    except loader.AssuranceFrameworkError as exc:
        return str(exc)


def _assurance_status_indexes(assurance_status: dict[str, Any] | None) -> dict[str, Any]:
    status = assurance_status or {}
    fr_by_id = {
        item.get("id"): item
        for item in status.get("frs", []) or []
        if item.get("id")
    }
    tbt_by_id = {
        item.get("id"): item
        for item in status.get("tbts", []) or []
        if item.get("id")
    }
    row_by_id = {
        item.get("id"): item
        for item in status.get("compliance_rows", []) or []
        if item.get("id")
    }
    rows_by_fr: dict[str, list[dict[str, Any]]] = {}
    rows_by_tbt: dict[str, list[dict[str, Any]]] = {}
    for row in row_by_id.values():
        for fr_id in row.get("fr_refs") or []:
            rows_by_fr.setdefault(fr_id, []).append(row)
        for tbt_id in row.get("tbt_refs") or []:
            rows_by_tbt.setdefault(tbt_id, []).append(row)
    return {
        "fr_by_id": fr_by_id,
        "tbt_by_id": tbt_by_id,
        "row_by_id": row_by_id,
        "rows_by_fr": rows_by_fr,
        "rows_by_tbt": rows_by_tbt,
    }


def _target_key(target: dict[str, Any] | None, fallback: str = "") -> str | None:
    target = target or {}
    target_type = target.get("type", "")
    ref = target.get("ref", "") or fallback
    if target_type == "ruleset_row":
        ruleset = target.get("ruleset", "")
        row = target.get("row") or ref
        return f"row:{ruleset}:{row}" if ruleset and row else None
    if target_type in {"fr", "tbt", "criterion", "gate", "evidence"} and ref:
        return f"{target_type}:{ref}"
    if ref.startswith("FR-"):
        return f"fr:{ref}"
    if ref.startswith("TBT-"):
        return f"tbt:{ref}"
    if ref.startswith("GATE-"):
        return f"gate:{ref}"
    if ref.startswith("CRIT-") or ref.startswith("G"):
        return f"criterion:{ref}"
    if ":" in ref:
        ruleset, _, row = ref.partition(":")
        return f"row:{ruleset}:{row}" if ruleset and row else None
    return None


def _control_effect(record: dict[str, Any], kind: str, default_effect: str) -> dict[str, Any]:
    return {
        "id": record.get("id", ""),
        "kind": kind,
        "status_effect": record.get("status_effect") or default_effect,
        "approval_status": record.get("approval_status", "pending"),
        "reason": record.get("reason", ""),
        "approved_by": record.get("approved_by", ""),
        "approved_at": record.get("approved_at", ""),
        "signature_ref": record.get("signature_ref", ""),
    }


def _gate_exception_indexes(assurance_instance: dict[str, Any] | None) -> dict[str, Any]:
    instance = assurance_instance or {}
    controls_by_target: dict[str, list[dict[str, Any]]] = {}
    decisions_by_target: dict[str, list[dict[str, Any]]] = {}
    for kind, records, default_effect in (
        ("waiver", instance.get("waivers") or [], "waived"),
        ("compensating_control", instance.get("compensating_controls") or [], "compensating_control"),
    ):
        for record in records:
            key = _target_key(record.get("target_ref"), record.get("target", ""))
            if not key:
                continue
            controls_by_target.setdefault(key, []).append(_control_effect(record, kind, default_effect))

    for decision in instance.get("decisions") or []:
        if decision.get("criterion"):
            key = f"criterion:{decision.get('criterion')}"
        else:
            key = f"gate:{decision.get('gate', '')}"
        if key.endswith(":"):
            continue
        decisions_by_target.setdefault(key, []).append({
            "id": decision.get("id", ""),
            "kind": "decision",
            "readiness_status": decision.get("readiness_status", ""),
            "outcome": decision.get("outcome", ""),
            "decided_by": decision.get("decided_by", ""),
            "decision_ref": decision.get("decision_ref", ""),
            "signature_ref": decision.get("signature_ref", ""),
        })
    return {"controls_by_target": controls_by_target, "decisions_by_target": decisions_by_target}


def _approved_control_effect(effects: list[dict[str, Any]]) -> dict[str, Any] | None:
    approved = [
        effect for effect in effects
        if effect.get("approval_status") in {"approved", "waived"}
    ]
    if not approved:
        return None
    approved.sort(key=lambda effect: 0 if effect.get("status_effect") == "compensating_control" else 1)
    return approved[0]


def _readiness_to_gate_status(readiness_status: str) -> str:
    return {
        "ready": "met",
        "blocked": "blocked",
        "partial": "partial",
        "manual_review": "manual",
        "waived": "manual",
    }.get(readiness_status, "manual")


def _scanner_blockers_for_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
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


def _status_to_evidence_state(status: str) -> str:
    if status in {"passed", "satisfied", "met", "observed"}:
        return "met"
    if status in {"failed", "missing", "not_observed", "blocked"}:
        return "missing"
    return "manual"


def _target_dir_from_manifest(report_dir: Path) -> Path | None:
    try:
        import json
        manifest = json.loads((report_dir / "evidence-manifest.json").read_text())
        target_dir = manifest.get("target_dir")
        return Path(target_dir) if target_dir else None
    except Exception:
        return None


def _status_badge(status: str) -> str:
    labels = {
        "met": "Met",
        "partial": "Partial",
        "blocked": "Blocked",
        "manual": "Manual review",
    }
    return f'<span class="gate-status gate-status-{html.escape(status)}">{labels.get(status, status)}</span>'


def _render_role_row(role: dict[str, Any]) -> str:
    party_type = role.get("party_type", "other")
    return (
        f'<tr><td><code>{html.escape(role.get("id", ""))}</code></td>'
        f'<td><strong>{html.escape(role.get("title", ""))}</strong>'
        f'<span>{html.escape(party_type)}</span></td></tr>'
    )


def _render_process(
    process: dict[str, Any],
    role_lookup: dict[str, dict[str, Any]],
    target_dir: Path | None,
    fr_catalog: Any | None,
    fr_evidence: dict[str, tuple[str, list[dict]]],
    target_evidence: dict[str, dict[str, Any]],
    resolved_status: dict[str, Any],
    gate_exceptions: dict[str, Any],
) -> str:
    gates = sorted(process.get("gates") or [], key=lambda g: g.get("sequence", 0))
    gate_blocks = []
    for gate in gates:
        state = _compute_gate_state(
            gate,
            role_lookup=role_lookup,
            target_dir=target_dir,
            fr_catalog=fr_catalog,
            fr_evidence=fr_evidence,
            target_evidence=target_evidence,
            resolved_status=resolved_status,
            gate_exceptions=gate_exceptions,
        )
        gate_blocks.append(_render_gate(gate, state, role_lookup))

    return (
        f'<section class="process-block">'
        f'<div class="card-head"><h2>{html.escape(process.get("title", ""))}</h2>'
        f'<span class="meta">{html.escape(process.get("id", ""))}</span></div>'
        f'<p class="process-desc">{html.escape(process.get("description", ""))}</p>'
        f'<div class="gate-list">{"".join(gate_blocks)}</div>'
        f'</section>'
    )


def _render_gate(gate: dict[str, Any], state: dict[str, Any], role_lookup: dict[str, dict[str, Any]]) -> str:
    role_items = []
    for role_req in gate.get("required_roles") or []:
        role = role_lookup.get(role_req.get("role", ""), {})
        required = role_req.get("required", True)
        assigned = role_req.get("party") or role_req.get("approval_ref") or role_req.get("status") in ("approved", "waived")
        role_items.append(
            '<li class="%s"><strong>%s</strong> <span>%s</span><em>%s</em></li>' % (
                "role-ok" if assigned or not required else "role-missing",
                html.escape(role.get("title") or role_req.get("role", "")),
                html.escape(role_req.get("responsibility", "")),
                html.escape(role_req.get("party") or role_req.get("status") or ("required" if required else "optional")),
            )
        )

    criterion_rows = []
    for criterion in state["criteria"]:
        ev_items = "".join(
            '<li class="%s"><code>%s</code> %s</li>' % (
                "evidence-ok" if ev["status"] == "met" else "evidence-missing" if ev["status"] == "missing" else "evidence-manual",
                html.escape(ev["type"]),
                html.escape(ev["label"]),
            )
            for ev in criterion["evidence"]
        )
        criterion_rows.append(
            f'<tr class="criterion-row criterion-{html.escape(criterion["status"])}">'
            f'<td><code>{html.escape(criterion["id"])}</code></td>'
            f'<td><strong>{html.escape(criterion["title"])}</strong>'
            f'<div class="criterion-desc">{html.escape(criterion.get("description", ""))}</div>'
            f'<ul class="evidence-list">{ev_items}</ul></td>'
            f'<td>{_status_badge(criterion["status"])}</td></tr>'
        )

    blockers = "".join(f'<li>{html.escape(b)}</li>' for b in state["blockers"])
    blocker_html = f'<div class="gate-blockers"><strong>Blocking continuation</strong><ul>{blockers}</ul></div>' if blockers else ""

    return (
        f'<article class="gate-card gate-{html.escape(state["status"])}">'
        f'<div class="gate-head"><div><span class="gate-sequence">Gate {gate.get("sequence", "")}</span>'
        f'<h3>{html.escape(gate.get("title", ""))}</h3></div>{_status_badge(state["status"])}</div>'
        f'<p>{html.escape(gate.get("description", ""))}</p>'
        f'<div class="gate-meta"><span>Continuation: <code>{html.escape(gate.get("continuation_rule", "all_mandatory_criteria_met"))}</code></span>'
        f'<span>{state["met_criteria"]}/{state["required_criteria"]} mandatory criteria met</span></div>'
        f'<div class="gate-roles"><strong>Required parties</strong><ul>{"".join(role_items)}</ul></div>'
        f'{blocker_html}'
        f'<table class="matrix process-criteria-table"><thead><tr><th>Criterion</th><th>Evidence</th><th>Status</th></tr></thead>'
        f'<tbody>{"".join(criterion_rows)}</tbody></table>'
        f'</article>'
    )


def _compute_gate_state(
    gate: dict[str, Any],
    *,
    role_lookup: dict[str, dict[str, Any]],
    target_dir: Path | None,
    fr_catalog: Any | None,
    fr_evidence: dict[str, tuple[str, list[dict]]],
    target_evidence: dict[str, dict[str, Any]],
    resolved_status: dict[str, Any] | None = None,
    gate_exceptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gate_exceptions = gate_exceptions or {}
    blockers: list[str] = []
    role_blockers = 0
    for role_req in gate.get("required_roles") or []:
        if role_req.get("required", True) is False:
            continue
        role_id = role_req.get("role", "")
        if role_id not in role_lookup:
            blockers.append(f"Unknown required role: {role_id}")
            role_blockers += 1
            continue
        approved = role_req.get("status") in ("approved", "waived")
        assigned = bool(role_req.get("party") or role_req.get("approval_ref") or approved)
        if not assigned:
            role_title = role_lookup.get(role_id, {}).get("title", role_id)
            blockers.append(f"{role_title} is not assigned for {role_req.get('responsibility', 'gate role')}")
            role_blockers += 1

    criterion_states = []
    required_criteria = 0
    met_criteria = 0
    manual_count = 0
    missing_count = 0
    scanner_blockers: list[dict[str, Any]] = []
    for criterion in gate.get("criteria") or []:
        cstate = _compute_criterion_state(
            criterion,
            target_dir,
            fr_catalog,
            fr_evidence,
            target_evidence,
            resolved_status or {},
            gate_exceptions,
        )
        criterion_states.append(cstate)
        scanner_blockers.extend(cstate.get("scanner_blockers", []))
        if cstate["required"]:
            required_criteria += 1
            if cstate["status"] == "met":
                met_criteria += 1
            elif cstate["status"] == "manual":
                manual_count += 1
                blockers.append(f"{criterion.get('id')}: manual evidence/review still required")
            elif cstate["status"] == "blocked":
                missing_count += 1
                blockers.append(f"{criterion.get('id')}: {cstate['reason']}")

    gate_key = f"gate:{gate.get('id', '')}"
    gate_controls = (gate_exceptions.get("controls_by_target") or {}).get(gate_key, [])
    gate_decisions = (gate_exceptions.get("decisions_by_target") or {}).get(gate_key, [])
    approved_control = _approved_control_effect(gate_controls)
    decision = gate_decisions[-1] if gate_decisions else None

    if decision and decision.get("readiness_status"):
        status = _readiness_to_gate_status(decision.get("readiness_status", ""))
        blockers.append(f"{decision.get('id')}: gate decision resolved as {decision.get('readiness_status')}")
    elif approved_control:
        status = "manual"
        blockers.append(f"{approved_control.get('id')}: reviewed {approved_control.get('kind')} applies to gate")
    elif role_blockers or missing_count:
        status = "blocked"
    elif manual_count:
        status = "manual"
    elif required_criteria and met_criteria == required_criteria:
        status = "met"
    else:
        status = "partial"

    return {
        "status": status,
        "blockers": blockers,
        "scanner_blockers": scanner_blockers,
        "scanner_blocker_count": len(scanner_blockers),
        "assurance_controls": gate_controls,
        "decisions": gate_decisions,
        "criteria": criterion_states,
        "required_criteria": required_criteria,
        "met_criteria": met_criteria,
    }


def _compute_criterion_state(
    criterion: dict[str, Any],
    target_dir: Path | None,
    fr_catalog: Any | None,
    fr_evidence: dict[str, tuple[str, list[dict]]],
    target_evidence: dict[str, dict[str, Any]],
    resolved_status: dict[str, Any] | None = None,
    gate_exceptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_states = []
    required = criterion.get("required", True)
    for evidence in criterion.get("evidence") or []:
        evidence_states.append(_compute_evidence_state(
            evidence,
            target_dir,
            fr_catalog,
            fr_evidence,
            target_evidence,
            resolved_status or {},
        ))

    required_evidence = [e for e in evidence_states if e["required"]]
    scanner_blockers = [
        blocker
        for evidence in required_evidence
        for blocker in evidence.get("scanner_blockers", [])
    ]
    criterion_key = f"criterion:{criterion.get('id', '')}"
    gate_exceptions = gate_exceptions or {}
    criterion_controls = (gate_exceptions.get("controls_by_target") or {}).get(criterion_key, [])
    criterion_decisions = (gate_exceptions.get("decisions_by_target") or {}).get(criterion_key, [])
    approved_control = _approved_control_effect(criterion_controls)
    decision = criterion_decisions[-1] if criterion_decisions else None
    if not required_evidence:
        status = "manual"
        reason = "no machine-checkable evidence declared"
    elif decision and decision.get("readiness_status"):
        status = _readiness_to_gate_status(decision.get("readiness_status", ""))
        reason = f"decision {decision.get('id')} resolved criterion as {decision.get('readiness_status')}"
        if status != "blocked":
            scanner_blockers = []
    elif approved_control:
        status = "manual"
        reason = f"reviewed {approved_control.get('kind')} {approved_control.get('id')} applies"
        scanner_blockers = []
    elif scanner_blockers:
        status = "blocked"
        labels = [
            f"{b.get('tool', 'scanner')} {b.get('mapping_id') or b.get('compliance_row', '')}".strip()
            for b in scanner_blockers[:3]
        ]
        reason = "blocking scanner evidence: " + ", ".join(labels)
    elif all(e["status"] == "met" for e in required_evidence):
        status = "met"
        reason = ""
    elif any(e["status"] == "missing" for e in required_evidence):
        status = "blocked"
        missing = [e["label"] for e in required_evidence if e["status"] == "missing"]
        reason = "missing evidence: " + ", ".join(missing[:3])
    else:
        status = "manual"
        reason = "manual or pending evidence remains"

    return {
        "id": criterion.get("id", ""),
        "title": criterion.get("title", ""),
        "description": criterion.get("description", ""),
        "required": required,
        "profiles": _normalise_profiles(criterion.get("profiles"), None),
        "status": status,
        "reason": reason,
        "scanner_blockers": scanner_blockers,
        "scanner_blocker_count": len(scanner_blockers),
        "assurance_controls": criterion_controls,
        "decisions": criterion_decisions,
        "evidence": evidence_states,
    }


def _compute_evidence_state(
    evidence: dict[str, Any],
    target_dir: Path | None,
    fr_catalog: Any | None,
    fr_evidence: dict[str, tuple[str, list[dict]]],
    target_evidence: dict[str, dict[str, Any]],
    resolved_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    etype = evidence.get("type", "")
    ref = evidence.get("ref", "")
    explicit = evidence.get("status")
    label = evidence.get("label") or ref
    required = evidence.get("required", True)
    resolved_status = resolved_status or {}
    scanner_blockers: list[dict[str, Any]] = []
    resolved_record: dict[str, Any] | None = None

    if explicit in ("met", "waived"):
        status = "met"
    elif explicit in ("missing",):
        status = "missing"
    elif explicit in ("pending", "manual"):
        status = "manual"
    elif etype == "fr":
        resolved_record = (resolved_status.get("fr_by_id") or {}).get(ref)
        scanner_blockers = _scanner_blockers_for_rows((resolved_status.get("rows_by_fr") or {}).get(ref, []))
        has_fr = bool(fr_catalog and ref in fr_catalog.fr_ids)
        ev_status = (resolved_record or {}).get("status") or fr_evidence.get(ref, ("missing", []))[0]
        if not has_fr or ev_status in ("failed", "missing"):
            status = "missing"
        elif ev_status == "partial":
            status = "manual"
        else:
            status = "met"
    elif etype in ("test", "scanner") or ref.startswith("TBT-"):
        resolved_record = (resolved_status.get("tbt_by_id") or {}).get(ref)
        scanner_blockers = _scanner_blockers_for_rows((resolved_status.get("rows_by_tbt") or {}).get(ref, []))
        tbt_status = (resolved_record or {}).get("status") or (target_evidence.get("tbt_status") or {}).get(ref)
        if tbt_status:
            status = _status_to_evidence_state(tbt_status)
        else:
            status = "manual"
    elif etype == "ruleset_row":
        resolved_record = (resolved_status.get("row_by_id") or {}).get(ref)
        scanner_blockers = _scanner_blockers_for_rows([resolved_record] if resolved_record else [])
        row_status = (resolved_record or {}).get("status")
        status = _status_to_evidence_state(row_status) if row_status else "manual"
    elif etype in ("manual", "document", "screenshot", "approval"):
        evidence_record = (target_evidence.get("evidence_by_id") or {}).get(ref)
        if evidence_record:
            result_status = evidence_record.get("result_status")
            if result_status == "passed":
                status = "met"
            elif result_status in ("failed", "missing"):
                status = "missing"
            else:
                status = "manual"
        else:
            if ref.startswith("EVD-"):
                status = "missing"
            else:
                path = Path(ref)
                if target_dir and not path.is_absolute():
                    path = target_dir / ref
                status = "met" if path.exists() else "manual"
    else:
        status = "manual"

    if (resolved_record or {}).get("status") in {"waived", "compensating_control"}:
        scanner_blockers = []
        status = "manual"
    elif scanner_blockers and required:
        status = "missing"

    return {
        "type": etype,
        "ref": ref,
        "label": label,
        "required": required,
        "status": status,
        "resolved_status": (resolved_record or {}).get("status", ""),
        "scanner_blockers": scanner_blockers,
        "scanner_blocker_count": len(scanner_blockers),
        "profiles": _normalise_profiles(evidence.get("profiles"), None),
    }


def _target_evidence_indexes(evidence_bundle: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    bundle = evidence_bundle or {}
    evidence_by_id: dict[str, dict[str, Any]] = {}
    statuses_by_tbt: dict[str, list[str]] = {}
    for evidence in bundle.get("evidence") or []:
        evidence_id = evidence.get("id")
        produced_by = evidence.get("produced_by")
        if evidence_id:
            evidence_by_id[evidence_id] = evidence
        if produced_by:
            statuses_by_tbt.setdefault(produced_by, []).append(evidence.get("result_status", "missing"))

    tbt_status: dict[str, str] = {}
    for tbt_id, statuses in statuses_by_tbt.items():
        if "failed" in statuses:
            tbt_status[tbt_id] = "failed"
        elif "missing" in statuses:
            tbt_status[tbt_id] = "missing"
        elif statuses and all(status == "passed" for status in statuses):
            tbt_status[tbt_id] = "passed"
        else:
            tbt_status[tbt_id] = "partial"
    return {"evidence_by_id": evidence_by_id, "tbt_status": tbt_status}


def _assurance_framework_error(message: str) -> str:
    return (
        '<section class="card"><div class="callout"><strong>Assurance framework error:</strong><br>'
        f'{html.escape(message)}<br><br>'
        'Fix the assurance framework and rescan.</div></section>'
    )
