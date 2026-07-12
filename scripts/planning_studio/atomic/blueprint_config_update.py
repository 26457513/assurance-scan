from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from artifact_hashing import file_sha256
from load_fr_catalog import load_fr_catalog


def _project_fr_id(blueprint_fr_id: str) -> str:
    return blueprint_fr_id.replace("FR-BP-", "FR-", 1)


def _project_tbt_id(blueprint_tbt_id: str) -> str:
    return blueprint_tbt_id.replace("TBT-BP-", "TBT-", 1)


def _tailoring_for(decision: dict[str, Any], *, target: str, source_id: str = "") -> list[dict[str, Any]]:
    selected = []
    for item in decision.get("tailoring") or []:
        item_target = item.get("target", target)
        item_source = item.get("source_id", source_id)
        if item_target == target and (not item_source or not source_id or item_source == source_id):
            selected.append(item)
    return selected


def _tailored_id(default_id: str, decision: dict[str, Any], *, target: str, source_id: str = "") -> str:
    for item in _tailoring_for(decision, target=target, source_id=source_id):
        if item.get("field") == "id" and item.get("to"):
            return str(item["to"])
    return default_id


def _apply_tailoring(value: dict[str, Any], decision: dict[str, Any], *, target: str, source_id: str = "") -> dict[str, Any]:
    updated = deepcopy(value)
    for item in _tailoring_for(decision, target=target, source_id=source_id):
        field = item.get("field")
        if not field or field == "id":
            continue
        if "to" in item:
            updated[str(field)] = deepcopy(item["to"])
    return updated


def _replace_string(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_string(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_string(item, replacements) for key, item in value.items()}
    return value


def _source_basis(source_ref: dict[str, Any], item_id: str) -> list[dict[str, Any]]:
    basis = {
        "type": "blueprint_catalog",
        "ref": f"{source_ref.get('id', '')}:{item_id}",
    }
    if source_ref.get("sha256"):
        basis["sha256"] = source_ref["sha256"]
    return [basis]


def build_config_update_from_blueprint_decisions(
    *,
    project: str,
    run_id: str,
    proposal: dict[str, Any],
    decision_log: dict[str, Any],
    blueprint_paths: list[Path],
    generated_at: str | None = None,
) -> dict[str, Any]:
    catalogs = [load_fr_catalog(path).raw for path in blueprint_paths]
    source_refs_by_path = {
        str(path): {
            "path": str(path),
            "kind": "fr_catalog_blueprint",
            "version": path.parent.name,
            "sha256": file_sha256(path, prefixed=True),
            "used_for": "Blueprint FR/TBT source for project config proposal",
        }
        for path in blueprint_paths
    }
    source_refs_by_id: dict[str, dict[str, Any]] = {
        source.get("id", ""): source
        for source in proposal.get("source_blueprints") or []
        if source.get("id")
    }
    fr_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    tbt_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for path, catalog in zip(blueprint_paths, catalogs):
        source_ref = source_refs_by_id.get(catalog.get("project", "")) or {
            "id": catalog.get("project", path.parent.parent.name),
            "version": path.parent.name,
            "path": str(path),
            "sha256": file_sha256(path, prefixed=True),
        }
        for fr in catalog.get("frs") or []:
            fr_by_id[fr["id"]] = (fr, source_ref)
        for tbt in catalog.get("tbts") or []:
            tbt_by_id[tbt["id"]] = (tbt, source_ref)

    candidate_by_id = {
        candidate["id"]: candidate
        for candidate in proposal.get("candidates") or []
    }
    accepted_decisions = [
        decision for decision in decision_log.get("decisions") or []
        if decision.get("decision") in {"accepted_as_is", "tailored"}
    ]
    fr_updates: list[dict[str, Any]] = []
    review_required: list[dict[str, str]] = []
    for decision in accepted_decisions:
        candidate = candidate_by_id.get(decision.get("candidate"))
        if not candidate:
            review_required.append({
                "item": str(decision.get("candidate", "unknown-candidate")),
                "question": "Decision references a missing blueprint candidate.",
                "why": "A config update cannot be generated without the original blueprint candidate context.",
            })
            continue
        blueprint_fr_id = candidate["blueprint_fr"]
        fr_entry = fr_by_id.get(blueprint_fr_id)
        if not fr_entry:
            review_required.append({
                "item": blueprint_fr_id,
                "question": "Blueprint FR was not found in the supplied blueprint catalogs.",
                "why": "A config update cannot be generated without the source FR.",
            })
            continue
        blueprint_fr, source_ref = fr_entry
        project_fr_id = _tailored_id(_project_fr_id(blueprint_fr_id), decision, target="fr", source_id=blueprint_fr_id)
        fr_fields = _apply_tailoring(blueprint_fr, decision, target="fr", source_id=blueprint_fr_id)
        fr_fields.pop("id", None)
        fr_fields["derived_from"] = {
            "source_type": "blueprint_fr",
            "source_id": blueprint_fr_id,
            "source_version": str(source_ref.get("version", "")),
            "source_path": str(source_ref.get("path", "")),
            "source_hash": str(source_ref.get("sha256", "")),
            "source_item": blueprint_fr_id,
            "tailoring": _tailoring_for(decision, target="fr", source_id=blueprint_fr_id),
            "review_status": "accepted",
            "rationale": decision.get("reason", ""),
        }
        fr_updates.append({
            "operation": "add_fr",
            "fr_id": project_fr_id,
            "review_status": "proposed",
            "proposed_fields": fr_fields,
            "source_basis": _source_basis(source_ref, blueprint_fr_id),
            "rationale": decision.get("reason", "Accepted blueprint FR for this project."),
            "confidence": "medium",
        })

        tbt_replacements: dict[str, str] = {blueprint_fr_id: project_fr_id}
        for blueprint_tbt_id in candidate.get("blueprint_tbts") or []:
            tbt_replacements[blueprint_tbt_id] = _tailored_id(
                _project_tbt_id(blueprint_tbt_id),
                decision,
                target="tbt",
                source_id=blueprint_tbt_id,
            )
        for blueprint_tbt_id in candidate.get("blueprint_tbts") or []:
            tbt_entry = tbt_by_id.get(blueprint_tbt_id)
            if not tbt_entry:
                review_required.append({
                    "item": blueprint_tbt_id,
                    "question": "Blueprint TBT was not found in the supplied blueprint catalogs.",
                    "why": "A config update cannot be generated without the source TBT.",
                })
                continue
            blueprint_tbt, tbt_source_ref = tbt_entry
            project_tbt_id = tbt_replacements[blueprint_tbt_id]
            tbt_fields = _replace_string(
                _apply_tailoring(blueprint_tbt, decision, target="tbt", source_id=blueprint_tbt_id),
                tbt_replacements,
            )
            tbt_fields.pop("id", None)
            tbt_fields["derived_from"] = {
                "source_type": "blueprint_tbt",
                "source_id": blueprint_tbt_id,
                "source_version": str(tbt_source_ref.get("version", "")),
                "source_path": str(tbt_source_ref.get("path", "")),
                "source_hash": str(tbt_source_ref.get("sha256", "")),
                "source_item": blueprint_tbt_id,
                "tailoring": _tailoring_for(decision, target="tbt", source_id=blueprint_tbt_id),
                "review_status": "accepted",
                "rationale": decision.get("reason", ""),
            }
            fr_updates.append({
                "operation": "add_tbt",
                "fr_id": project_fr_id,
                "tbt_id": project_tbt_id,
                "review_status": "proposed",
                "proposed_fields": tbt_fields,
                "source_basis": _source_basis(tbt_source_ref, blueprint_tbt_id),
                "rationale": decision.get("reason", "Accepted blueprint TBT for this project."),
                "confidence": "medium",
            })

    source_inputs = [
        {
            "path": str(path),
            "kind": ref["kind"],
            "version": ref["version"],
            "sha256": ref["sha256"],
            "used_for": ref["used_for"],
        }
        for path, ref in source_refs_by_path.items()
    ]
    return {
        "schema_version": 1,
        "mode": "config_update_proposal",
        "project": project,
        "run_id": run_id,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source_inputs": source_inputs,
        "fr_catalog_updates": fr_updates,
        "compliance_mapping_pack_updates": [],
        "assurance_framework_or_instance_updates": [],
        "manual_evidence_updates": [],
        "native_test_mapping_updates": [],
        "uncertain_mappings": [],
        "review_required": review_required,
    }
