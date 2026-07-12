#!/usr/bin/env python3
"""Validate an agent-authored config update proposal.

The proposal is advisory: this command validates shape and optional
cross-references, but it does not apply changes to any config file.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from load_fr_catalog import FrCatalogError, load_fr_catalog
from load_target_artifacts import TargetArtifactError, load_target_artifact


def _load_optional(path: Path | None, kind: str) -> dict[str, Any] | None:
    if not path:
        return None
    return load_target_artifact(path, kind).raw


def _fr_indexes(path: Path | None) -> tuple[set[str], set[str]]:
    if not path:
        return set(), set()
    catalog = load_fr_catalog(path).raw
    return (
        {fr["id"] for fr in catalog.get("frs", []) if fr.get("id")},
        {tbt["id"] for tbt in catalog.get("tbts", []) if tbt.get("id")},
    )


def _framework_indexes(raw: dict[str, Any] | None) -> set[str]:
    if not raw:
        return set()
    ids: set[str] = set()
    for role in raw.get("roles") or []:
        if role.get("id"):
            ids.add(role["id"])
    for process in raw.get("processes") or []:
        if process.get("id"):
            ids.add(process["id"])
        for gate in process.get("gates") or []:
            if gate.get("id"):
                ids.add(gate["id"])
            for criterion in gate.get("criteria") or []:
                if criterion.get("id"):
                    ids.add(criterion["id"])
    return ids


def _framework_reference_sets(raw: dict[str, Any] | None) -> tuple[set[str], set[str], set[str]]:
    if not raw:
        return set(), set(), set()
    roles = {role["id"] for role in raw.get("roles") or [] if role.get("id")}
    gates: set[str] = set()
    criteria: set[str] = set()
    for process in raw.get("processes") or []:
        for gate in process.get("gates") or []:
            if gate.get("id"):
                gates.add(gate["id"])
            for criterion in gate.get("criteria") or []:
                if criterion.get("id"):
                    criteria.add(criterion["id"])
    return roles, gates, criteria


def _cross_validate(
    proposal: dict[str, Any],
    *,
    fr_ids: set[str],
    tbt_ids: set[str],
    ruleset_rows: set[tuple[str, str]],
    framework_ids: set[str],
    framework_roles: set[str],
    framework_gates: set[str],
    framework_criteria: set[str],
) -> list[str]:
    errors: list[str] = []

    for update in proposal.get("fr_catalog_updates") or []:
        operation = update.get("operation")
        fr_id = update.get("fr_id")
        tbt_id = update.get("tbt_id")
        if fr_ids and operation in {"update_fr", "deprecate_fr", "add_tbt", "update_tbt", "deprecate_tbt"} and fr_id not in fr_ids:
            errors.append(f"fr_catalog_updates: {operation} references unknown FR {fr_id}")
        if tbt_ids and operation in {"update_tbt", "deprecate_tbt"} and tbt_id not in tbt_ids:
            errors.append(f"fr_catalog_updates: {operation} references unknown TBT {tbt_id}")
        if operation in {"add_tbt", "update_tbt"} and not tbt_id:
            errors.append(f"fr_catalog_updates: {operation} requires tbt_id")
        if operation == "add_fr" and fr_ids and fr_id in fr_ids:
            errors.append(f"fr_catalog_updates: add_fr would duplicate existing FR {fr_id}")
        if operation == "add_tbt" and tbt_ids and tbt_id in tbt_ids:
            errors.append(f"fr_catalog_updates: add_tbt would duplicate existing TBT {tbt_id}")

    for update in proposal.get("compliance_mapping_pack_updates") or []:
        ruleset = update.get("ruleset")
        row = update.get("row_id")
        if ruleset_rows and (ruleset, row) not in ruleset_rows:
            errors.append(f"compliance_mapping_pack_updates: unknown ruleset row {ruleset} {row}")
        for fr_id in update.get("fr_refs") or []:
            if fr_ids and fr_id not in fr_ids:
                errors.append(f"compliance_mapping_pack_updates: unknown FR {fr_id}")
        for tbt_id in update.get("tbt_refs") or []:
            if tbt_ids and tbt_id not in tbt_ids:
                errors.append(f"compliance_mapping_pack_updates: unknown TBT {tbt_id}")

    for section in ("assurance_framework_or_instance_updates", "manual_evidence_updates"):
        for update in proposal.get(section) or []:
            target = update.get("target") or {}
            kind = target.get("kind")
            target_id = target.get("id")
            if kind == "fr" and fr_ids and target_id not in fr_ids:
                errors.append(f"{section}: unknown FR target {target_id}")
            elif kind == "tbt" and tbt_ids and target_id not in tbt_ids:
                errors.append(f"{section}: unknown TBT target {target_id}")
            elif kind in {"process", "gate", "criterion", "role"} and framework_ids and target_id not in framework_ids:
                errors.append(f"{section}: unknown {kind} target {target_id}")
            proposed = update.get("proposed_fields") or {}
            for gate_ref in (proposed.get("gate"), proposed.get("gate_id")):
                if gate_ref and framework_gates and gate_ref not in framework_gates:
                    errors.append(f"{section}: proposed gate references unknown gate {gate_ref}")
            for role_ref in (proposed.get("role"), proposed.get("role_id")):
                if role_ref and framework_roles and role_ref not in framework_roles:
                    errors.append(f"{section}: proposed role references unknown role {role_ref}")
            for criterion_ref in (proposed.get("criterion"), proposed.get("criterion_id")):
                if criterion_ref and framework_criteria and criterion_ref not in framework_criteria:
                    errors.append(f"{section}: proposed criterion references unknown criterion {criterion_ref}")
            for requirement in proposed.get("requirements") or proposed.get("append_requirements") or []:
                if requirement.get("type") == "ruleset_row" and ruleset_rows:
                    key = (requirement.get("ruleset"), requirement.get("row") or requirement.get("ref"))
                    if key not in ruleset_rows:
                        errors.append(f"{section}: proposed requirement references unknown ruleset row {key[0]} {key[1]}")

    proposed_fr_ids = {
        update.get("fr_id")
        for update in proposal.get("fr_catalog_updates") or []
        if update.get("operation") == "add_fr" and update.get("fr_id")
    }
    proposed_tbt_ids = {
        update.get("tbt_id")
        for update in proposal.get("fr_catalog_updates") or []
        if update.get("operation") == "add_tbt" and update.get("tbt_id")
    }
    for update in proposal.get("native_test_mapping_updates") or []:
        operation = update.get("operation")
        target = update.get("target") or {}
        fr_id = target.get("fr")
        tbt_id = target.get("tbt")
        new_fr = update.get("new_fr") or {}
        new_tbt = update.get("new_tbt") or {}
        if operation == "map_native_test_to_existing_tbt":
            if fr_ids and fr_id not in fr_ids:
                errors.append(f"native_test_mapping_updates: unknown target FR {fr_id}")
            if tbt_ids and tbt_id not in tbt_ids:
                errors.append(f"native_test_mapping_updates: unknown target TBT {tbt_id}")
        elif operation == "create_tbt_under_existing_fr":
            if fr_ids and fr_id not in fr_ids:
                errors.append(f"native_test_mapping_updates: unknown parent FR {fr_id}")
            new_tbt_id = new_tbt.get("id")
            if not new_tbt_id:
                errors.append("native_test_mapping_updates: create_tbt_under_existing_fr requires new_tbt.id")
            if new_tbt_id and (new_tbt_id in tbt_ids or new_tbt_id in proposed_tbt_ids):
                errors.append(f"native_test_mapping_updates: new TBT would duplicate {new_tbt_id}")
        elif operation == "create_new_fr_and_tbt":
            new_fr_id = new_fr.get("id")
            new_tbt_id = new_tbt.get("id")
            if not new_fr_id:
                errors.append("native_test_mapping_updates: create_new_fr_and_tbt requires new_fr.id")
            if not new_tbt_id:
                errors.append("native_test_mapping_updates: create_new_fr_and_tbt requires new_tbt.id")
            if new_fr_id and (new_fr_id in fr_ids or new_fr_id in proposed_fr_ids):
                errors.append(f"native_test_mapping_updates: new FR would duplicate {new_fr_id}")
            if new_tbt_id and (new_tbt_id in tbt_ids or new_tbt_id in proposed_tbt_ids):
                errors.append(f"native_test_mapping_updates: new TBT would duplicate {new_tbt_id}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path, help="Config update proposal JSON produced by the agent prompt")
    parser.add_argument("--fr-catalog", type=Path, help="FR catalog used by the scan")
    parser.add_argument("--ruleset", type=Path, help="Compliance ruleset catalog for cross-reference checks")
    parser.add_argument("--assurance-framework", type=Path, help="Assurance framework catalog for gate/role checks")
    args = parser.parse_args()

    try:
        proposal = load_target_artifact(args.proposal, "config_update_proposal").raw
        fr_ids, tbt_ids = _fr_indexes(args.fr_catalog)
        ruleset = _load_optional(args.ruleset, "ruleset")
        framework = _load_optional(args.assurance_framework, "assurance_framework")
    except (TargetArtifactError, FrCatalogError) as exc:
        print(f"ERROR: {exc}")
        return 1

    ruleset_rows = {
        (ruleset.get("ruleset"), row.get("id"))
        for row in (ruleset or {}).get("rows", [])
        if row.get("id")
    }
    framework_roles, framework_gates, framework_criteria = _framework_reference_sets(framework)
    errors = _cross_validate(
        proposal,
        fr_ids=fr_ids,
        tbt_ids=tbt_ids,
        ruleset_rows=ruleset_rows,
        framework_ids=_framework_indexes(framework),
        framework_roles=framework_roles,
        framework_gates=framework_gates,
        framework_criteria=framework_criteria,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    update_count = sum(
        len(proposal.get(section) or [])
        for section in (
            "fr_catalog_updates",
            "compliance_mapping_pack_updates",
            "assurance_framework_or_instance_updates",
            "manual_evidence_updates",
            "native_test_mapping_updates",
        )
    )
    print(f"OK config update proposal: {update_count} proposed updates")
    print(f"  uncertain mappings: {len(proposal.get('uncertain_mappings') or [])}")
    print(f"  review items: {len(proposal.get('review_required') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
