#!/usr/bin/env python3
"""Apply selected, reviewed config update proposal entries to output files.

This command never mutates input files in place. Provide explicit output paths
for every config artifact you want to write.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from load_fr_catalog import FrCatalogError, load_fr_catalog
from load_target_artifacts import TargetArtifactError, load_target_artifact, validate_assurance_instance_against_framework


APPLYABLE_SECTIONS = {
    "fr_catalog_updates",
    "compliance_mapping_pack_updates",
    "native_test_mapping_updates",
}
REVIEW_ONLY_SECTIONS = {
    "assurance_framework_or_instance_updates",
}
CONDITIONAL_SECTIONS = {
    "manual_evidence_updates",
}
UPDATE_SECTIONS = APPLYABLE_SECTIONS | REVIEW_ONLY_SECTIONS | CONDITIONAL_SECTIONS


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _commit_validated_json_writes(writes: list[tuple[Path, dict[str, Any], str, Path | None]]) -> None:
    temp_paths: list[tuple[Path, Path]] = []
    try:
        for path, data, kind, assurance_framework in writes:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            temp_path = Path(temp_name)
            with os.fdopen(fd, "w") as handle:
                handle.write(json.dumps(data, indent=2) + "\n")
            _validate_output(temp_path, kind, assurance_framework=assurance_framework)
            temp_paths.append((path, temp_path))
        for path, temp_path in temp_paths:
            temp_path.replace(path)
    except Exception:
        for _, temp_path in temp_paths:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        raise


def _selector_map(selectors: list[str]) -> dict[str, set[int] | None]:
    selected: dict[str, set[int] | None] = {}
    for selector in selectors:
        if ":" not in selector:
            raise ValueError(f"Invalid selector '{selector}'. Use section:index, e.g. fr_catalog_updates:1")
        section, raw_index = selector.split(":", 1)
        if section not in UPDATE_SECTIONS:
            raise ValueError(f"Unknown section '{section}'. Expected one of {sorted(UPDATE_SECTIONS)}")
        if raw_index == "*":
            selected[section] = None
            continue
        try:
            index = int(raw_index)
        except ValueError as exc:
            raise ValueError(f"Invalid selector index '{raw_index}' in '{selector}'") from exc
        if index < 1:
            raise ValueError(f"Selector index must be 1-based: {selector}")
        selected.setdefault(section, set())
        if selected[section] is not None:
            selected[section].add(index)
    return selected


def _selected_updates(proposal: dict[str, Any], selectors: dict[str, set[int] | None]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for section, picked in selectors.items():
        updates = proposal.get(section) or []
        if picked is None:
            out[section] = list(updates)
            continue
        missing = sorted(index for index in picked if index > len(updates))
        if missing:
            raise ValueError(f"{section}: selector index out of range: {missing}")
        out[section] = [updates[index - 1] for index in sorted(picked)]
    return out


def _is_applyable_update(section: str, update: dict[str, Any]) -> bool:
    if section in APPLYABLE_SECTIONS:
        return True
    if section == "assurance_framework_or_instance_updates":
        operation = update.get("operation")
        target = update.get("target") or {}
        if operation in {"add_instance_mapping", "update_instance_mapping"}:
            return target.get("kind") in {"criterion", "gate", "role"}
        if operation in {"add_decision", "update_decision"}:
            return target.get("kind") in {"gate", "decision"}
        if operation in {"add_waiver", "update_waiver"}:
            return target.get("kind") in {"fr", "tbt", "ruleset_row", "gate", "criterion", "waiver"}
        if operation in {"add_compensating_control", "update_compensating_control"}:
            return target.get("kind") in {"fr", "tbt", "ruleset_row", "gate", "criterion", "compensating_control"}
        return False
    if section == "manual_evidence_updates":
        target = update.get("target") or {}
        proposed = update.get("proposed_fields") or {}
        target_kind = target.get("kind")
        if target_kind in {"fr", "tbt", "criterion"}:
            return True
        if target_kind == "gate":
            return bool(proposed.get("criterion") or proposed.get("criterion_id"))
        if target_kind == "role":
            return bool((proposed.get("gate") or proposed.get("gate_id")) and (proposed.get("role") or proposed.get("role_id") or target.get("id")))
    return False


def _apply_mode(section: str, update: dict[str, Any]) -> str:
    return "applyable" if _is_applyable_update(section, update) else "review-only"


def _list_selectors(proposal: dict[str, Any]) -> str:
    lines = ["Selectable proposal entries:"]
    for section in sorted(UPDATE_SECTIONS):
        updates = proposal.get(section) or []
        if not updates:
            continue
        lines.append(f"\n{section}:")
        for index, update in enumerate(updates, start=1):
            label = _update_label(update)
            confidence = update.get("confidence", "unknown")
            lines.append(f"  {section}:{index}  {label}  [{confidence}; {_apply_mode(section, update)}]")
    return "\n".join(lines)


def _update_label(update: dict[str, Any]) -> str:
    bits = [str(update.get("operation", "update"))]
    if update.get("fr_id"):
        bits.append(str(update["fr_id"]))
    if update.get("tbt_id"):
        bits.append(str(update["tbt_id"]))
    if update.get("ruleset") and update.get("row_id"):
        bits.append(f"{update['ruleset']} {update['row_id']}")
    if update.get("scanner"):
        bits.append(str(update["scanner"]))
    native_test = update.get("native_test") or {}
    if native_test.get("native_path"):
        bits.append(str(native_test["native_path"]))
    return " / ".join(bits)


def _stamp_metadata(item: dict[str, Any], update: dict[str, Any], *, reviewer: str, reviewed_at: str) -> None:
    metadata = item.setdefault("metadata", {})
    metadata["config_update_review"] = {
        "review_status": "accepted",
        "reviewed_by": reviewer,
        "reviewed_at": reviewed_at,
        "source_basis": update.get("source_basis") or [],
        "rationale": update.get("rationale", ""),
        "confidence": update.get("confidence", ""),
    }


def _merge_fields(target: dict[str, Any], proposed_fields: dict[str, Any]) -> None:
    for key, value in proposed_fields.items():
        target[key] = deepcopy(value)


def _default_fr_owner(fr: dict[str, Any]) -> str:
    text = " ".join(str(fr.get(key, "")) for key in ("category", "title", "description")).lower()
    rules = (
        (("auth", "access", "session", "role", "permission", "administrator"), "auth-team"),
        (("data", "pii", "privacy", "sensitivity", "classification"), "data-security-team"),
        (("audit", "logging", "log", "trace"), "platform-security-team"),
        (("document", "storage", "corpus", "ingestion", "metadata", "source"), "document-platform-team"),
        (("ai", "agent", "prompt", "model", "ontology", "knowledge"), "ai-platform-team"),
    )
    for terms, owner in rules:
        if any(term in text for term in terms):
            return owner
    return "product-security-team"


def _normalise_fr_fields(fr: dict[str, Any]) -> None:
    fr.pop("owner", None)
    fr.setdefault("lifecycle_status", "in_scope")
    if not fr.get("assignments"):
        fr["assignments"] = [{
            "party": _default_fr_owner(fr),
            "responsibility": "owner",
            "source": "derived_from_category",
        }]


def _normalise_tbt_fields(tbt: dict[str, Any]) -> None:
    tbt.setdefault("compliance", [])


def _apply_fr_updates(catalog: dict[str, Any], updates: list[dict[str, Any]], *, reviewer: str, reviewed_at: str) -> dict[str, Any]:
    next_catalog = deepcopy(catalog)
    frs = next_catalog.setdefault("frs", [])
    tbts = next_catalog.setdefault("tbts", [])
    fr_by_id = {fr.get("id"): fr for fr in frs}
    tbt_by_id = {tbt.get("id"): tbt for tbt in tbts}

    for update in updates:
        operation = update.get("operation")
        fr_id = update.get("fr_id")
        tbt_id = update.get("tbt_id")
        proposed_fields = deepcopy(update.get("proposed_fields") or {})

        if operation == "add_fr":
            if fr_id in fr_by_id:
                raise ValueError(f"FR {fr_id} already exists")
            new_fr = {"id": fr_id, **proposed_fields}
            _normalise_fr_fields(new_fr)
            frs.append(new_fr)
            fr_by_id[fr_id] = new_fr
            _stamp_metadata(new_fr, update, reviewer=reviewer, reviewed_at=reviewed_at)
        elif operation == "update_fr":
            fr = fr_by_id.get(fr_id)
            if not fr:
                raise ValueError(f"FR {fr_id} not found")
            _merge_fields(fr, proposed_fields)
            _normalise_fr_fields(fr)
            _stamp_metadata(fr, update, reviewer=reviewer, reviewed_at=reviewed_at)
        elif operation == "deprecate_fr":
            fr = fr_by_id.get(fr_id)
            if not fr:
                raise ValueError(f"FR {fr_id} not found")
            fr["lifecycle_status"] = "retired"
            _stamp_metadata(fr, update, reviewer=reviewer, reviewed_at=reviewed_at)
        elif operation == "add_tbt":
            if tbt_id in tbt_by_id:
                raise ValueError(f"TBT {tbt_id} already exists")
            new_tbt = {"id": tbt_id, **proposed_fields}
            new_tbt.setdefault("proves", [fr_id])
            _normalise_tbt_fields(new_tbt)
            tbts.append(new_tbt)
            tbt_by_id[tbt_id] = new_tbt
            _stamp_metadata(new_tbt, update, reviewer=reviewer, reviewed_at=reviewed_at)
        elif operation == "update_tbt":
            tbt = tbt_by_id.get(tbt_id)
            if not tbt:
                raise ValueError(f"TBT {tbt_id} not found")
            _merge_fields(tbt, proposed_fields)
            _normalise_tbt_fields(tbt)
            _stamp_metadata(tbt, update, reviewer=reviewer, reviewed_at=reviewed_at)
        elif operation == "deprecate_tbt":
            tbt = tbt_by_id.get(tbt_id)
            if not tbt:
                raise ValueError(f"TBT {tbt_id} not found")
            tbt["lifecycle_status"] = "deprecated"
            _stamp_metadata(tbt, update, reviewer=reviewer, reviewed_at=reviewed_at)
        else:
            raise ValueError(f"Unsupported FR catalog operation: {operation}")

    return next_catalog


def _manual_expected_evidence(update: dict[str, Any]) -> dict[str, Any]:
    proposed = deepcopy(update.get("proposed_fields") or {})
    evidence_type = update.get("evidence_type")
    entry: dict[str, Any] = {
        "type": evidence_type,
        "required": proposed.get("required", True),
        "strength": proposed.get("minimum_strength") or proposed.get("strength") or "manual_review",
    }
    match = deepcopy(proposed.get("match") or {})
    if proposed.get("paths"):
        match["paths"] = proposed["paths"]
    if proposed.get("tags"):
        match["tags"] = proposed["tags"]
    if match:
        entry["match"] = match
    if proposed.get("format"):
        entry["format"] = proposed["format"]
    if proposed.get("source"):
        entry["source"] = proposed["source"]
    if proposed.get("notes"):
        entry["notes"] = proposed["notes"]
    else:
        entry["notes"] = update.get("rationale", "")
    return entry


def _apply_manual_evidence_updates(catalog: dict[str, Any], updates: list[dict[str, Any]], *, reviewer: str, reviewed_at: str) -> dict[str, Any]:
    next_catalog = deepcopy(catalog)
    frs = next_catalog.setdefault("frs", [])
    tbts = next_catalog.setdefault("tbts", [])
    fr_by_id = {fr.get("id"): fr for fr in frs}
    tbt_by_id = {tbt.get("id"): tbt for tbt in tbts}

    for update in updates:
        operation = update.get("operation")
        if operation not in {"add_expected_manual_evidence", "update_expected_manual_evidence"}:
            raise ValueError(f"Unsupported manual evidence operation: {operation}")
        target = update.get("target") or {}
        target_kind = target.get("kind")
        target_id = target.get("id")
        if target_kind == "tbt":
            tbt = tbt_by_id.get(target_id)
            if not tbt:
                raise ValueError(f"TBT {target_id} not found")
            evidence = _manual_expected_evidence(update)
            existing = tbt.setdefault("expected_evidence", [])
            existing.append(evidence)
            _stamp_metadata(tbt, update, reviewer=reviewer, reviewed_at=reviewed_at)
        elif target_kind == "fr":
            fr = fr_by_id.get(target_id)
            if not fr:
                raise ValueError(f"FR {target_id} not found")
            metadata = fr.setdefault("metadata", {})
            manual = metadata.setdefault("expected_manual_evidence", [])
            manual.append({
                "type": update.get("evidence_type"),
                "proposed_fields": deepcopy(update.get("proposed_fields") or {}),
                "review_status": "accepted",
                "reviewed_by": reviewer,
                "reviewed_at": reviewed_at,
                "source_basis": deepcopy(update.get("source_basis") or []),
                "rationale": update.get("rationale", ""),
                "confidence": update.get("confidence", ""),
            })
            _stamp_metadata(fr, update, reviewer=reviewer, reviewed_at=reviewed_at)
        else:
            raise ValueError(
                f"manual_evidence_updates target {target_kind} is review-only in this version. "
                "Only FR and TBT manual evidence can be applied to an FR catalog."
            )

    return next_catalog


def _source_basis_for_mapping(update: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source in update.get("source_basis") or []:
        item = deepcopy(source)
        if "type" in item and "kind" not in item:
            item["kind"] = item.pop("type")
        out.append(item)
    return out


def _mapping_common(update: dict[str, Any], *, reviewer: str, reviewed_at: str) -> dict[str, Any]:
    return {
        "review_status": "accepted",
        "reviewed_by": reviewer,
        "reviewed_at": reviewed_at,
        "review_decision": "accepted_from_config_update_proposal",
        "review_notes": update.get("rationale", ""),
        "source_basis": _source_basis_for_mapping(update),
        "rationale": update.get("rationale", ""),
        "confidence": update.get("confidence", "medium"),
    }


def _compliance_mapping_id(update: dict[str, Any]) -> str:
    if update.get("mapping_id"):
        return str(update["mapping_id"])
    fr_part = "-".join(update.get("fr_refs") or ["NO-FR"])
    row = str(update.get("row_id", "row")).replace(".", "_")
    return f"MAP-{update.get('ruleset')}-{row}-{fr_part}"


def _scanner_mapping_id(update: dict[str, Any]) -> str:
    if update.get("mapping_id"):
        return str(update["mapping_id"])
    tbt_part = "-".join(update.get("tbt_refs") or ["NO-TBT"])
    return f"MAP-{str(update.get('scanner', 'scanner')).upper()}-{tbt_part}"


def _apply_compliance_updates(pack: dict[str, Any], updates: list[dict[str, Any]], *, reviewer: str, reviewed_at: str) -> dict[str, Any]:
    next_pack = deepcopy(pack)
    mappings = next_pack.setdefault("mappings", [])
    by_id = {mapping.get("id"): mapping for mapping in mappings}

    for update in updates:
        operation = update.get("operation")
        mapping_id = _compliance_mapping_id(update)
        if operation == "deprecate_mapping":
            mapping = by_id.get(mapping_id)
            if not mapping:
                raise ValueError(f"Compliance mapping {mapping_id} not found")
            mapping["review_status"] = "stale"
            mapping["review_notes"] = update.get("rationale", "")
            continue

        fields = {
            "id": mapping_id,
            **_mapping_common(update, reviewer=reviewer, reviewed_at=reviewed_at),
            "row_id": update.get("row_id"),
            "fr_refs": deepcopy(update.get("fr_refs") or []),
            "tbt_refs": deepcopy(update.get("tbt_refs") or []),
            "sufficiency": deepcopy(update.get("sufficiency") or {}),
        }
        if update.get("scope_status"):
            fields["scope_status"] = update["scope_status"]

        if operation == "add_mapping":
            if mapping_id in by_id:
                raise ValueError(f"Compliance mapping {mapping_id} already exists")
            mappings.append(fields)
            by_id[mapping_id] = fields
        elif operation == "update_mapping":
            mapping = by_id.get(mapping_id)
            if not mapping:
                raise ValueError(f"Compliance mapping {mapping_id} not found")
            mapping.clear()
            mapping.update(fields)
        else:
            raise ValueError(f"Unsupported compliance mapping operation: {operation}")

    if next_pack.get("pack"):
        next_pack["pack"]["updated_at"] = reviewed_at
    return next_pack


def _native_mapping_review(update: dict[str, Any], *, reviewer: str, reviewed_at: str) -> dict[str, Any]:
    return {
        "review_status": "accepted",
        "reviewed_by": reviewer,
        "reviewed_at": reviewed_at,
        "operation": update.get("operation", ""),
        "source_basis": deepcopy(update.get("source_basis") or []),
        "rationale": update.get("rationale", ""),
        "confidence": update.get("confidence", ""),
    }


def _find_native_test_entry(pack: dict[str, Any], native_test: dict[str, Any]) -> dict[str, Any]:
    pack_id = native_test.get("pack_id")
    native_path = native_test.get("native_path")
    tests = pack.setdefault("tests", [])
    for entry in tests:
        if pack_id and entry.get("pack_id") == pack_id:
            return entry
    for entry in tests:
        if native_path and entry.get("native_path") == native_path:
            return entry
    raise ValueError(f"Native test entry not found in assurance test pack: {pack_id or native_path}")


def _apply_native_test_mapping_updates(pack: dict[str, Any], updates: list[dict[str, Any]], *, reviewer: str, reviewed_at: str) -> dict[str, Any]:
    next_pack = deepcopy(pack)
    for update in updates:
        operation = update.get("operation")
        native_test = update.get("native_test") or {}
        entry = _find_native_test_entry(next_pack, native_test)
        entry["mapping_review"] = _native_mapping_review(update, reviewer=reviewer, reviewed_at=reviewed_at)

        if operation == "map_native_test_to_existing_tbt":
            target = update.get("target") or {}
            fr_id = target.get("fr")
            tbt_id = target.get("tbt")
            if not fr_id or not tbt_id:
                raise ValueError("map_native_test_to_existing_tbt requires target.fr and target.tbt")
            entry["tbt"] = tbt_id
            frs = list(entry.get("frs") or [])
            if fr_id not in frs:
                frs.append(fr_id)
            entry["frs"] = frs
            if entry.get("assessment") in {"candidate_inspiration", "needs_design"}:
                entry["assessment"] = "useful_with_wrapper"
            if entry.get("safety") == "review_required":
                entry["safety"] = "non_destructive"
            entry["rationale"] = update.get("rationale", entry.get("rationale", ""))
        elif operation == "mark_not_assurance_relevant":
            entry.pop("tbt", None)
            entry["frs"] = []
            entry["assessment"] = "not_assurance_relevant"
            entry["review_disposition"] = "reviewed_not_evidence"
            entry["safety"] = "non_destructive"
            entry["rationale"] = update.get("rationale", entry.get("rationale", ""))
        elif operation == "mark_project_specific_only":
            entry.pop("tbt", None)
            entry["frs"] = []
            entry["assessment"] = "bespoke_project_only"
            entry["review_disposition"] = "bespoke_project_only"
            entry["safety"] = "review_required"
            entry["rationale"] = update.get("rationale", entry.get("rationale", ""))
        elif operation == "leave_unmapped":
            entry.pop("tbt", None)
            entry["frs"] = []
            entry["review_disposition"] = "needs_mapping_review" if update.get("review_status") == "needs_review" else "left_unmapped"
            entry["safety"] = "review_required"
            entry["rationale"] = update.get("rationale", entry.get("rationale", ""))
        elif operation in {"create_tbt_under_existing_fr", "create_new_fr_and_tbt"}:
            raise ValueError(
                f"{operation} also changes the FR catalog. Apply the accepted FR/TBT creation through fr_catalog_updates, "
                "then map the native test to the reviewed TBT."
            )
        else:
            raise ValueError(f"Unsupported native test mapping operation: {operation}")

    summary = next_pack.setdefault("summary", {})
    tests = next_pack.get("tests") or []
    summary["mapped_native"] = sum(1 for item in tests if item.get("native_path") and item.get("tbt"))
    summary["unmapped_native"] = sum(
        1
        for item in tests
        if item.get("native_path")
        and not item.get("tbt")
        and item.get("assessment") not in {"not_assurance_relevant", "bespoke_project_only"}
    )
    summary["not_assurance_relevant_native"] = sum(1 for item in tests if item.get("native_path") and item.get("assessment") == "not_assurance_relevant")
    summary["bespoke_project_only_native"] = sum(1 for item in tests if item.get("native_path") and item.get("assessment") == "bespoke_project_only")
    next_pack["updated_at"] = reviewed_at
    return next_pack


def _instance_mapping_common(update: dict[str, Any], *, reviewer: str, reviewed_at: str) -> dict[str, Any]:
    return {
        "config_update_review": {
            "review_status": "accepted",
            "reviewed_by": reviewer,
            "reviewed_at": reviewed_at,
            "source_basis": deepcopy(update.get("source_basis") or []),
            "rationale": update.get("rationale", ""),
            "confidence": update.get("confidence", ""),
        }
    }


def _criterion_id_for_instance_update(update: dict[str, Any]) -> str:
    target = update.get("target") or {}
    proposed = update.get("proposed_fields") or {}
    if proposed.get("criterion"):
        return str(proposed["criterion"])
    if target.get("kind") == "criterion":
        return str(target.get("id") or "")
    if proposed.get("criterion_id"):
        return str(proposed["criterion_id"])
    raise ValueError(f"{update.get('operation')} targeting {target.get('kind')} requires proposed_fields.criterion")


def _requirement_from_proposed(item: dict[str, Any]) -> dict[str, Any]:
    req_type = item.get("type")
    if not req_type:
        raise ValueError("Instance mapping requirement is missing type")
    requirement = {
        "type": req_type,
        "ref": item.get("ref") or item.get("id") or item.get("evidence") or item.get("row") or "",
    }
    if not requirement["ref"]:
        raise ValueError(f"Instance mapping requirement {req_type} is missing ref")
    for key in ("ruleset", "row", "evidence"):
        if item.get(key):
            requirement[key] = item[key]
    return requirement


def _manual_requirement_from_update(update: dict[str, Any]) -> dict[str, Any]:
    proposed = update.get("proposed_fields") or {}
    target = update.get("target") or {}
    evidence_type = update.get("evidence_type")
    if evidence_type == "approval" or proposed.get("approval_ref"):
        ref = proposed.get("approval_ref") or proposed.get("ref") or proposed.get("evidence") or f"APPROVAL-{target.get('id')}"
        return {"type": "approval", "ref": str(ref)}
    paths = proposed.get("paths") or []
    path_ref = paths[0] if paths else None
    ref = proposed.get("ref") or proposed.get("artifact") or proposed.get("artifact_id") or path_ref or f"MANUAL-{target.get('id')}"
    evidence = proposed.get("evidence") or proposed.get("evidence_id") or ref
    return {"type": "manual_artifact", "ref": str(ref), "evidence": str(evidence)}


def _append_unique_requirement(mapping: dict[str, Any], requirement: dict[str, Any]) -> None:
    requirements = mapping.setdefault("requirements", [])
    identity = (
        requirement.get("type"),
        requirement.get("ref"),
        requirement.get("ruleset"),
        requirement.get("row"),
        requirement.get("evidence"),
    )
    for existing in requirements:
        if (
            existing.get("type"),
            existing.get("ref"),
            existing.get("ruleset"),
            existing.get("row"),
            existing.get("evidence"),
        ) == identity:
            return
    requirements.append(requirement)


def _role_assignment_key(update: dict[str, Any]) -> tuple[str, str]:
    target = update.get("target") or {}
    proposed = update.get("proposed_fields") or {}
    gate = proposed.get("gate") or proposed.get("gate_id")
    role = proposed.get("role") or proposed.get("role_id")
    if target.get("kind") == "role":
        role = role or target.get("id")
    if target.get("kind") == "gate":
        gate = gate or target.get("id")
    if not gate or not role:
        raise ValueError("Role instance updates require gate and role in proposed_fields")
    return str(gate), str(role)


def _decision_id(update: dict[str, Any]) -> str:
    target = update.get("target") or {}
    proposed = update.get("proposed_fields") or {}
    if proposed.get("id"):
        return str(proposed["id"])
    if target.get("kind") == "decision" and target.get("id"):
        return str(target["id"])
    gate = proposed.get("gate") or proposed.get("gate_id") or (target.get("id") if target.get("kind") == "gate" else None)
    if gate:
        return f"DEC-{gate}"
    raise ValueError("Decision updates require proposed_fields.id, target decision id, or a gate target")


def _decision_gate(update: dict[str, Any]) -> str:
    target = update.get("target") or {}
    proposed = update.get("proposed_fields") or {}
    gate = proposed.get("gate") or proposed.get("gate_id") or (target.get("id") if target.get("kind") == "gate" else None)
    if not gate:
        raise ValueError("Decision updates require gate in target or proposed_fields")
    return str(gate)


def _controlled_exception_id(update: dict[str, Any], *, kind: str, prefix: str) -> str:
    target = update.get("target") or {}
    proposed = update.get("proposed_fields") or {}
    if proposed.get("id"):
        return str(proposed["id"])
    if target.get("kind") == kind and target.get("id"):
        return str(target["id"])
    if target.get("id"):
        safe = str(target["id"]).replace(":", "-").replace("/", "-")
        return f"{prefix}-{safe}"
    raise ValueError(f"{kind.replace('_', ' ').title()} updates require proposed_fields.id or a target id")


def _waiver_id(update: dict[str, Any]) -> str:
    return _controlled_exception_id(update, kind="waiver", prefix="WVR")


def _compensating_control_id(update: dict[str, Any]) -> str:
    return _controlled_exception_id(update, kind="compensating_control", prefix="CMP")


def _controlled_exception_target(update: dict[str, Any], *, label: str) -> str:
    target = update.get("target") or {}
    proposed = update.get("proposed_fields") or {}
    if proposed.get("target"):
        return str(proposed["target"])
    target_kind = target.get("kind")
    if target_kind == "ruleset_row" and target.get("ruleset") and target.get("row"):
        return f"{target['ruleset']}:{target['row']}"
    if target.get("id"):
        return str(target["id"])
    raise ValueError(f"{label} updates require a target id")


def _waiver_target(update: dict[str, Any]) -> str:
    return _controlled_exception_target(update, label="Waiver")


def _compensating_control_target(update: dict[str, Any]) -> str:
    return _controlled_exception_target(update, label="Compensating control")


def _apply_assurance_instance_updates(instance: dict[str, Any], updates: list[dict[str, Any]], *, reviewer: str, reviewed_at: str) -> dict[str, Any]:
    next_instance = deepcopy(instance)
    criterion_mappings = next_instance.setdefault("criterion_mappings", [])
    mappings_by_criterion = {
        mapping.get("criterion"): mapping
        for mapping in criterion_mappings
        if mapping.get("criterion")
    }
    role_assignments = next_instance.setdefault("role_assignments", [])
    assignments_by_key = {
        (assignment.get("gate"), assignment.get("role")): assignment
        for assignment in role_assignments
        if assignment.get("gate") and assignment.get("role")
    }
    decisions = next_instance.setdefault("decisions", [])
    decisions_by_gate = {
        decision.get("gate"): decision
        for decision in decisions
        if decision.get("gate")
    }
    decisions_by_id = {
        decision.get("id"): decision
        for decision in decisions
        if decision.get("id")
    }
    waivers = next_instance.setdefault("waivers", [])
    waivers_by_id = {
        waiver.get("id"): waiver
        for waiver in waivers
        if waiver.get("id")
    }
    compensating_controls = next_instance.setdefault("compensating_controls", [])
    compensating_controls_by_id = {
        control.get("id"): control
        for control in compensating_controls
        if control.get("id")
    }

    for update in updates:
        operation = update.get("operation")
        target = update.get("target") or {}
        target_kind = target.get("kind")
        proposed = deepcopy(update.get("proposed_fields") or {})
        review_metadata = _instance_mapping_common(update, reviewer=reviewer, reviewed_at=reviewed_at)

        if operation in {"add_instance_mapping", "update_instance_mapping"} and target_kind in {"criterion", "gate"}:
            criterion_id = _criterion_id_for_instance_update(update)
            mapping = mappings_by_criterion.get(criterion_id)
            if operation == "add_instance_mapping" and mapping:
                raise ValueError(f"Assurance criterion mapping {criterion_id} already exists")
            if not mapping:
                mapping = {"criterion": criterion_id, "requirements": []}
                criterion_mappings.append(mapping)
                mappings_by_criterion[criterion_id] = mapping
            if proposed.get("requirements") is not None:
                mapping["requirements"] = [
                    _requirement_from_proposed(item)
                    for item in proposed.get("requirements") or []
                ]
            else:
                for item in proposed.get("append_requirements") or []:
                    _append_unique_requirement(mapping, _requirement_from_proposed(item))
            mapping.setdefault("metadata", {}).update(review_metadata)
        elif operation in {"add_instance_mapping", "update_instance_mapping"} and target_kind == "role":
            gate, role = _role_assignment_key(update)
            assignment = assignments_by_key.get((gate, role))
            if operation == "add_instance_mapping" and assignment:
                raise ValueError(f"Role assignment {gate}/{role} already exists")
            if not assignment:
                assignment = {"gate": gate, "role": role, "approval_status": proposed.get("approval_status", "pending")}
                role_assignments.append(assignment)
                assignments_by_key[(gate, role)] = assignment
            for key in ("party", "approval_status", "approval_ref", "notes"):
                if key in proposed:
                    assignment[key] = proposed[key]
            assignment.setdefault("metadata", {}).update(review_metadata)
        elif operation in {"add_decision", "update_decision"}:
            decision_id = _decision_id(update)
            gate = _decision_gate(update)
            decision = decisions_by_id.get(decision_id)
            if not decision and operation == "update_decision":
                decision = decisions_by_gate.get(gate)
            if operation == "add_decision" and decision:
                raise ValueError(f"Decision {decision_id} already exists")
            if not decision:
                readiness_status = proposed.get("readiness_status")
                if not readiness_status:
                    raise ValueError("Decision updates require proposed_fields.readiness_status")
                decision = {"id": decision_id, "gate": gate, "readiness_status": readiness_status}
                decisions.append(decision)
                decisions_by_id[decision_id] = decision
                decisions_by_gate[gate] = decision
            for key in ("gate", "readiness_status", "decided_by", "decided_at", "notes"):
                if key in proposed:
                    decision[key] = proposed[key]
            decision.setdefault("metadata", {}).update(review_metadata)
        elif operation in {"add_waiver", "update_waiver"}:
            waiver_id = _waiver_id(update)
            waiver = waivers_by_id.get(waiver_id)
            if operation == "add_waiver" and waiver:
                raise ValueError(f"Waiver {waiver_id} already exists")
            if not waiver:
                reason = proposed.get("reason") or update.get("rationale")
                approval_status = proposed.get("approval_status") or "pending"
                waiver = {
                    "id": waiver_id,
                    "target": _waiver_target(update),
                    "reason": reason,
                    "approval_status": approval_status,
                }
                waivers.append(waiver)
                waivers_by_id[waiver_id] = waiver
            for key in ("target", "target_ref", "reason", "approval_status", "status_effect", "scope", "expires_at", "review_due_at", "approved_by", "approved_at", "signature_ref", "evidence_refs", "notes"):
                if key in proposed:
                    waiver[key] = proposed[key]
            waiver.setdefault("metadata", {}).update(review_metadata)
        elif operation in {"add_compensating_control", "update_compensating_control"}:
            control_id = _compensating_control_id(update)
            control = compensating_controls_by_id.get(control_id)
            if operation == "add_compensating_control" and control:
                raise ValueError(f"Compensating control {control_id} already exists")
            if not control:
                reason = proposed.get("reason") or update.get("rationale")
                approval_status = proposed.get("approval_status") or "pending"
                control = {
                    "id": control_id,
                    "target": _compensating_control_target(update),
                    "reason": reason,
                    "approval_status": approval_status,
                }
                compensating_controls.append(control)
                compensating_controls_by_id[control_id] = control
            for key in ("target", "target_ref", "reason", "control_description", "approval_status", "status_effect", "scope", "expires_at", "review_due_at", "approved_by", "approved_at", "signature_ref", "evidence_refs", "notes"):
                if key in proposed:
                    control[key] = proposed[key]
            control.setdefault("metadata", {}).update(review_metadata)
        else:
            raise ValueError(f"Unsupported assurance instance operation: {operation} for target {target_kind}")

    return next_instance


def _apply_instance_manual_evidence(instance: dict[str, Any], updates: list[dict[str, Any]], *, reviewer: str, reviewed_at: str) -> dict[str, Any]:
    next_instance = deepcopy(instance)
    criterion_mappings = next_instance.setdefault("criterion_mappings", [])
    mappings_by_criterion = {
        mapping.get("criterion"): mapping
        for mapping in criterion_mappings
        if mapping.get("criterion")
    }
    role_assignments = next_instance.setdefault("role_assignments", [])
    assignments_by_key = {
        (assignment.get("gate"), assignment.get("role")): assignment
        for assignment in role_assignments
        if assignment.get("gate") and assignment.get("role")
    }
    decisions = next_instance.setdefault("decisions", [])
    decisions_by_gate = {
        decision.get("gate"): decision
        for decision in decisions
        if decision.get("gate")
    }

    for update in updates:
        target = update.get("target") or {}
        target_kind = target.get("kind")
        target_id = str(target.get("id") or "")
        proposed = update.get("proposed_fields") or {}
        review_metadata = _instance_mapping_common(update, reviewer=reviewer, reviewed_at=reviewed_at)

        if target_kind in {"criterion", "gate"}:
            criterion_id = proposed.get("criterion") or proposed.get("criterion_id") or (target_id if target_kind == "criterion" else None)
            if not criterion_id:
                raise ValueError("Gate manual evidence requires proposed_fields.criterion")
            mapping = mappings_by_criterion.get(str(criterion_id))
            if not mapping:
                mapping = {"criterion": str(criterion_id), "requirements": []}
                criterion_mappings.append(mapping)
                mappings_by_criterion[str(criterion_id)] = mapping
            _append_unique_requirement(mapping, _manual_requirement_from_update(update))
            mapping.setdefault("metadata", {}).update(review_metadata)
        elif target_kind == "role":
            gate, role = _role_assignment_key(update)
            assignment = assignments_by_key.get((gate, role))
            if not assignment:
                assignment = {"gate": gate, "role": role, "approval_status": proposed.get("approval_status", "pending")}
                role_assignments.append(assignment)
                assignments_by_key[(gate, role)] = assignment
            if update.get("evidence_type") == "approval":
                assignment["approval_ref"] = proposed.get("approval_ref") or proposed.get("ref") or assignment.get("approval_ref", "")
                assignment["approval_status"] = proposed.get("approval_status", assignment.get("approval_status", "pending"))
            if proposed.get("party"):
                assignment["party"] = proposed["party"]
            if proposed.get("notes"):
                assignment["notes"] = proposed["notes"]
            assignment.setdefault("metadata", {}).update(review_metadata)
        else:
            raise ValueError(f"Unsupported assurance-instance manual evidence target: {target_kind}")

    return next_instance


def _validate_output(path: Path, kind: str, *, assurance_framework: Path | None = None) -> None:
    if kind == "fr_catalog":
        load_fr_catalog(path)
        return
    artifact = load_target_artifact(path, kind)
    if kind == "assurance_instance" and assurance_framework:
        framework = load_target_artifact(assurance_framework, "assurance_framework").raw
        errors = validate_assurance_instance_against_framework(artifact.raw, framework)
        if errors:
            raise TargetArtifactError(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--select", action="append", default=[], help="1-based update selector, e.g. fr_catalog_updates:1 or compliance_mapping_pack_updates:*")
    parser.add_argument("--reviewed-by", required=False, help="Reviewer identity recorded on accepted outputs")
    parser.add_argument("--fr-catalog", type=Path)
    parser.add_argument("--fr-catalog-out", type=Path)
    parser.add_argument("--compliance-mapping-pack", type=Path)
    parser.add_argument("--compliance-mapping-pack-out", type=Path)
    parser.add_argument("--assurance-test-pack", type=Path)
    parser.add_argument("--assurance-test-pack-out", type=Path)
    parser.add_argument("--assurance-instance", type=Path)
    parser.add_argument("--assurance-instance-out", type=Path)
    parser.add_argument("--assurance-framework", type=Path, help="Optional framework used to validate reviewed assurance-instance references")
    parser.add_argument("--list", action="store_true", help="List selectable proposal entries and exit")
    args = parser.parse_args()

    try:
        proposal = load_target_artifact(args.proposal, "config_update_proposal").raw
        if args.list or not args.select:
            print(_list_selectors(proposal))
            if not args.select:
                print("\nNo changes written. Re-run with --select and explicit --*-out paths to apply reviewed entries.")
            return 0
        if not args.reviewed_by:
            print("ERROR: --reviewed-by is required when applying selected updates", file=sys.stderr)
            return 1
        selectors = _selector_map(args.select)
        selected = _selected_updates(proposal, selectors)
        for section, updates in selected.items():
            for update in updates:
                if not _is_applyable_update(section, update):
                    raise ValueError(
                        f"{section} selector targets a review-only item. Validate and review it, then apply it manually or add a dedicated applier."
                    )
        reviewed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        written: list[tuple[Path, str]] = []
        planned_writes: list[tuple[Path, dict[str, Any], str, Path | None]] = []
        fr_manual_updates = [
            update
            for update in selected.get("manual_evidence_updates", [])
            if (update.get("target") or {}).get("kind") in {"fr", "tbt"}
        ]
        instance_manual_updates = [
            update
            for update in selected.get("manual_evidence_updates", [])
            if (update.get("target") or {}).get("kind") in {"criterion", "gate", "role"}
        ]
        instance_updates = selected.get("assurance_framework_or_instance_updates", [])

        if selected.get("fr_catalog_updates") or fr_manual_updates:
            if not args.fr_catalog or not args.fr_catalog_out:
                raise ValueError("FR catalog and manual evidence updates require --fr-catalog and --fr-catalog-out")
            catalog = _load_json(args.fr_catalog)
            updated = catalog
            if selected.get("fr_catalog_updates"):
                updated = _apply_fr_updates(updated, selected["fr_catalog_updates"], reviewer=args.reviewed_by, reviewed_at=reviewed_at)
            if fr_manual_updates:
                updated = _apply_manual_evidence_updates(updated, fr_manual_updates, reviewer=args.reviewed_by, reviewed_at=reviewed_at)
            planned_writes.append((args.fr_catalog_out, updated, "fr_catalog", None))
            written.append((args.fr_catalog_out, "fr_catalog"))

        if instance_updates or instance_manual_updates:
            if not args.assurance_instance or not args.assurance_instance_out:
                raise ValueError("Assurance instance updates require --assurance-instance and --assurance-instance-out")
            instance = _load_json(args.assurance_instance)
            updated = instance
            if instance_updates:
                updated = _apply_assurance_instance_updates(updated, instance_updates, reviewer=args.reviewed_by, reviewed_at=reviewed_at)
            if instance_manual_updates:
                updated = _apply_instance_manual_evidence(updated, instance_manual_updates, reviewer=args.reviewed_by, reviewed_at=reviewed_at)
            planned_writes.append((args.assurance_instance_out, updated, "assurance_instance", args.assurance_framework))
            written.append((args.assurance_instance_out, "assurance_instance"))

        if selected.get("compliance_mapping_pack_updates"):
            if not args.compliance_mapping_pack or not args.compliance_mapping_pack_out:
                raise ValueError("Compliance mapping updates require --compliance-mapping-pack and --compliance-mapping-pack-out")
            pack = _load_json(args.compliance_mapping_pack)
            updated = _apply_compliance_updates(pack, selected["compliance_mapping_pack_updates"], reviewer=args.reviewed_by, reviewed_at=reviewed_at)
            planned_writes.append((args.compliance_mapping_pack_out, updated, "compliance_mapping_pack", None))
            written.append((args.compliance_mapping_pack_out, "compliance_mapping_pack"))

        if selected.get("native_test_mapping_updates"):
            if not args.assurance_test_pack or not args.assurance_test_pack_out:
                raise ValueError("Native test mapping updates require --assurance-test-pack and --assurance-test-pack-out")
            pack = _load_json(args.assurance_test_pack)
            updated = _apply_native_test_mapping_updates(pack, selected["native_test_mapping_updates"], reviewer=args.reviewed_by, reviewed_at=reviewed_at)
            planned_writes.append((args.assurance_test_pack_out, updated, "assurance_test_pack", None))
            written.append((args.assurance_test_pack_out, "assurance_test_pack"))
        if planned_writes:
            _commit_validated_json_writes(planned_writes)
    except (ValueError, TargetArtifactError, FrCatalogError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for path, kind in written:
        print(f"OK wrote {kind}: {path}")
    if not written:
        print("OK no selected updates required writable target files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
