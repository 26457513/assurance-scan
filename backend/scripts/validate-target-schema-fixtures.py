#!/usr/bin/env python3
"""Validate target schema review fixtures without external dependencies.

Target artifact loaders validate local shape where available. This script then
validates cross-file integrity: FR/TBT/evidence/ruleset/gate IDs, graph edges,
and basic uniqueness rules.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from load_fr_catalog import FrCatalogError, load_fr_catalog
from load_target_artifacts import TargetArtifactError, load_target_artifact

BACKEND_ROOT = Path(__file__).resolve().parent.parent


FIXTURE_NAMES = {
    "ruleset": "ruleset.example.json",
    "scanner_rules": "scanner-rules.example.json",
    "scanner_compliance_mapping_pack": "scanner-compliance-mapping-pack.example.json",
    "compliance_mapping_pack": "compliance-mapping-pack.example.json",
    "blueprint_compliance_mapping_pack": "blueprint-compliance-mapping-pack.example.json",
    "fr_catalog": "fr-catalog.example.json",
    "evidence_bundle": "evidence-bundle.example.json",
    "assurance_framework": "assurance-framework.example.json",
    "assurance_instance": "assurance-instance.example.json",
    "assurance_claim": "assurance-claim.example.json",
    "assurance_proof_bundle": "assurance-proof-bundle.example.json",
    "assurance_test_pack": "assurance-test-pack.example.json",
    "dashboard_payload": "dashboard-payload.example.json",
    "graph_manifest": "graph-manifest.example.json",
    "project_fr_board_state": "project-fr-board-state.example.json",
    "agent_prompt_plan": "agent-prompt-plan.example.json",
    "config_update_proposal": "config-update-proposal.example.json",
    "project_intake": "project-intake.example.json",
    "project_config_selection": "project-config-selection.example.json",
    "project_design_questionnaire": "project-design-questionnaire.example.json",
    "project_design_answers": "project-design-answers.example.json",
    "blueprint_selection_proposal": "blueprint-selection-proposal.example.json",
    "blueprint_decision_log": "blueprint-decision-log.example.json",
    "project_specific_requirements": "project-specific-requirements.example.json",
    "repository_analysis_summary": "repository-analysis-summary.example.json",
    "existing_evidence_mapping_proposal": "existing-evidence-mapping-proposal.example.json",
    "resolved_project_planning_contract": "resolved-project-planning-contract.example.json",
    "project_assurance_contract": "project-assurance-contract.example.json",
    "project_design_document_manifest": "project-design-document-manifest.example.json",
    "code_studio_handoff_pack": "code-studio-handoff-pack.example.json",
    "code_generator_handoff_pack": "code-generator-handoff-pack.example.json",
}

EXPECTED_SCHEMA_FILES = {
    "agent-prompt-plan.schema.json",
    "assurance-framework.schema.json",
    "assurance-instance.schema.json",
    "assurance-claim.schema.json",
    "assurance-proof-bundle.schema.json",
    "assurance-test-pack.schema.json",
    "authority-source-registry.schema.json",
    "compliance-pack.schema.json",
    "compliance-regime.schema.json",
    "dashboard-payload.schema.json",
    "evidence-bundle.schema.json",
    "evidence-mapping-pack.v2.schema.json",
    "fr-catalog.schema.json",
    "fr-catalog.v2.schema.json",
    "fr-catalog.v3.schema.json",
    "fr-compliance-mapping.schema.json",
    "graph-manifest.schema.json",
    "project-fr-board-state.schema.json",
    "glossary.schema.json",
    "compliance-mapping-pack.schema.json",
    "blueprint-compliance-mapping-pack.schema.json",
    "config-update-proposal.schema.json",
    "defs.schema.json",
    "ruleset.schema.json",
    "scanner-compliance-mapping-pack.schema.json",
    "scanner-rules.schema.json",
    "project-intake.schema.json",
    "project-config-selection.schema.json",
    "project-design-questionnaire.schema.json",
    "project-design-answers.schema.json",
    "blueprint-selection-proposal.schema.json",
    "blueprint-decision-log.schema.json",
    "project-specific-requirements.schema.json",
    "repository-analysis-summary.schema.json",
    "existing-evidence-mapping-proposal.schema.json",
    "resolved-project-planning-contract.schema.json",
    "project-assurance-contract.schema.json",
    "project-design-document-manifest.schema.json",
    "code-studio-handoff-pack.schema.json",
    "code-generator-handoff-pack.schema.json",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc


def require_unique(values: list[str], label: str, errors: list[str]) -> None:
    seen: set[str] = set()
    dupes: set[str] = set()
    for value in values:
        if value in seen:
            dupes.add(value)
        seen.add(value)
    for dupe in sorted(dupes):
        errors.append(f"duplicate {label}: {dupe}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=BACKEND_ROOT / "resources" / "fixtures" / "target-schemas",
        help="Directory containing target schema example JSON files.",
    )
    parser.add_argument(
        "--glossary",
        type=Path,
        default=BACKEND_ROOT / "resources" / "glossary" / "core-terms.json",
        help="Core glossary JSON to validate with the target schema set.",
    )
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=BACKEND_ROOT / "resources" / "schemas",
        help="Directory containing target JSON Schema files.",
    )
    args = parser.parse_args()

    fixture_dir = args.fixture_dir
    errors: list[str] = []
    docs: dict[str, Any] = {}
    schema_files = {path.name for path in args.schema_dir.glob("*.schema.json")}
    missing_schemas = EXPECTED_SCHEMA_FILES - schema_files
    extra_schemas = schema_files - EXPECTED_SCHEMA_FILES
    for name in sorted(missing_schemas):
        errors.append(f"missing target schema file: {args.schema_dir / name}")
    for name in sorted(extra_schemas):
        errors.append(f"unexpected target schema file: {args.schema_dir / name}")
    for name in sorted(schema_files & EXPECTED_SCHEMA_FILES):
        try:
            load_json(args.schema_dir / name)
        except ValueError as exc:
            errors.append(str(exc))
    artifact_kinds = {
        "ruleset": "ruleset",
        "scanner_rules": "scanner_rules",
        "scanner_compliance_mapping_pack": "scanner_compliance_mapping_pack",
        "compliance_mapping_pack": "compliance_mapping_pack",
        "blueprint_compliance_mapping_pack": "blueprint_compliance_mapping_pack",
        "evidence_bundle": "evidence_bundle",
        "assurance_framework": "assurance_framework",
        "assurance_instance": "assurance_instance",
        "assurance_claim": "assurance_claim",
        "assurance_proof_bundle": "assurance_proof_bundle",
        "assurance_test_pack": "assurance_test_pack",
        "dashboard_payload": "dashboard_payload",
        "graph_manifest": "graph_manifest",
        "project_fr_board_state": "project_fr_board_state",
        "agent_prompt_plan": "agent_prompt_plan",
        "config_update_proposal": "config_update_proposal",
        "project_intake": "project_intake",
        "project_config_selection": "project_config_selection",
        "project_design_questionnaire": "project_design_questionnaire",
        "project_design_answers": "project_design_answers",
        "blueprint_selection_proposal": "blueprint_selection_proposal",
        "blueprint_decision_log": "blueprint_decision_log",
        "project_specific_requirements": "project_specific_requirements",
        "repository_analysis_summary": "repository_analysis_summary",
        "existing_evidence_mapping_proposal": "existing_evidence_mapping_proposal",
        "resolved_project_planning_contract": "resolved_project_planning_contract",
        "project_assurance_contract": "project_assurance_contract",
        "project_design_document_manifest": "project_design_document_manifest",
        "code_studio_handoff_pack": "code_studio_handoff_pack",
        "code_generator_handoff_pack": "code_generator_handoff_pack",
    }

    for key, name in FIXTURE_NAMES.items():
        path = fixture_dir / name
        if not path.exists():
            errors.append(f"missing fixture: {path}")
            continue
        try:
            if key == "fr_catalog":
                docs[key] = load_fr_catalog(path).raw
            elif key in artifact_kinds:
                docs[key] = load_target_artifact(path, artifact_kinds[key]).raw
            else:
                docs[key] = load_json(path)
        except (ValueError, FrCatalogError, TargetArtifactError) as exc:
            errors.append(str(exc))
    try:
        docs["glossary"] = load_target_artifact(args.glossary, "glossary").raw
    except TargetArtifactError as exc:
        errors.append(str(exc))

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    ruleset = docs["ruleset"]
    scanner_rules = docs["scanner_rules"]
    scanner_compliance_mapping_pack = docs["scanner_compliance_mapping_pack"]
    compliance_mapping_pack = docs["compliance_mapping_pack"]
    blueprint_compliance_mapping_pack = docs["blueprint_compliance_mapping_pack"]
    fr_catalog = docs["fr_catalog"]
    evidence_bundle = docs["evidence_bundle"]
    assurance_framework = docs["assurance_framework"]
    assurance_instance = docs["assurance_instance"]
    assurance_test_pack = docs["assurance_test_pack"]
    dashboard_payload = docs["dashboard_payload"]
    agent_prompt_plan = docs["agent_prompt_plan"]
    config_update_proposal = docs["config_update_proposal"]
    glossary = docs["glossary"]

    ruleset_rows = {(ruleset["ruleset"], row["id"]) for row in ruleset.get("rows", [])}
    scanner_rule_ids = [rule["id"] for rule in scanner_rules.get("rules", [])]
    fr_ids = [fr["id"] for fr in fr_catalog.get("frs", [])]
    tbt_ids = [tbt["id"] for tbt in fr_catalog.get("tbts", [])]
    evidence_ids = [ev["id"] for ev in evidence_bundle.get("evidence", [])]
    role_ids = [role["id"] for role in assurance_framework.get("roles", [])]
    gate_ids = [
        gate["id"]
        for process in assurance_framework.get("processes", [])
        for gate in process.get("gates", [])
    ]
    criterion_ids = [
        criterion["id"]
        for process in assurance_framework.get("processes", [])
        for gate in process.get("gates", [])
        for criterion in gate.get("criteria", [])
    ]

    fr_set = set(fr_ids)
    tbt_set = set(tbt_ids)
    evidence_set = set(evidence_ids)
    role_set = set(role_ids)
    gate_set = set(gate_ids)
    criterion_set = set(criterion_ids)
    glossary_term_ids = [term["id"] for term in glossary.get("terms", [])]
    glossary_term_set = set(glossary_term_ids)
    waiver_ids = [waiver["id"] for waiver in assurance_instance.get("waivers", []) if waiver.get("id")]
    compensating_control_ids = [
        control["id"]
        for control in assurance_instance.get("compensating_controls", [])
        if control.get("id")
    ]
    decision_ids = [decision["id"] for decision in assurance_instance.get("decisions", []) if decision.get("id")]

    require_unique([row for _, row in ruleset_rows], "ruleset row id", errors)
    require_unique(scanner_rule_ids, "scanner rule id", errors)
    require_unique([mapping["id"] for mapping in scanner_compliance_mapping_pack.get("mappings", [])], "scanner compliance mapping id", errors)
    require_unique([mapping["id"] for mapping in compliance_mapping_pack.get("mappings", [])], "compliance mapping id", errors)
    require_unique(fr_ids, "FR id", errors)
    require_unique(tbt_ids, "TBT id", errors)
    require_unique(evidence_ids, "evidence id", errors)
    require_unique(role_ids, "role id", errors)
    require_unique(gate_ids, "gate id", errors)
    require_unique(criterion_ids, "criterion id", errors)
    require_unique(waiver_ids, "waiver id", errors)
    require_unique(compensating_control_ids, "compensating control id", errors)
    require_unique(decision_ids, "decision id", errors)
    require_unique(glossary_term_ids, "glossary term id", errors)

    for term in glossary.get("terms", []):
        for related in term.get("related_terms", []) or []:
            if related not in glossary_term_set:
                errors.append(f"glossary term {term['id']} references unknown related term {related}")

    compliance = scanner_compliance_mapping_pack.get("compliance") or {}
    if (compliance.get("ruleset"), compliance.get("version")) != (
        ruleset.get("ruleset"),
        ruleset.get("version"),
    ):
        errors.append(
            "scanner compliance mapping pack ruleset/version "
            f"{compliance.get('ruleset')} {compliance.get('version')} "
            f"does not match ruleset fixture {ruleset.get('ruleset')} {ruleset.get('version')}"
        )
    for mapping in scanner_compliance_mapping_pack.get("mappings", []):
        if mapping.get("review_status") == "accepted" and not mapping.get("reviewed_by"):
            errors.append(f"scanner compliance mapping {mapping['id']} is accepted without reviewed_by")
        targets = mapping.get("targets") or {}
        for row_ref in targets.get("compliance_rows", []):
            key = (row_ref.get("ruleset"), row_ref.get("row"))
            if key not in ruleset_rows:
                errors.append(f"scanner compliance mapping {mapping['id']} references unknown ruleset row {key}")
        level = mapping.get("mapping_level")
        if level == "compliance_row" and not targets.get("compliance_rows"):
            errors.append(f"scanner compliance mapping {mapping['id']} is row-level without row targets")
        if level == "compliance_domain" and not targets.get("compliance_domains"):
            errors.append(f"scanner compliance mapping {mapping['id']} is domain-level without domain targets")
        if level == "general_finding" and (targets.get("compliance_rows") or targets.get("compliance_domains")):
            errors.append(f"scanner compliance mapping {mapping['id']} is general_finding with compliance targets")

    if (compliance_mapping_pack.get("ruleset"), compliance_mapping_pack.get("ruleset_version")) != (
        ruleset.get("ruleset"),
        ruleset.get("version"),
    ):
        errors.append(
            "compliance mapping pack ruleset/version "
            f"{compliance_mapping_pack.get('ruleset')} {compliance_mapping_pack.get('ruleset_version')} "
            f"does not match ruleset fixture {ruleset.get('ruleset')} {ruleset.get('version')}"
        )
    for mapping in compliance_mapping_pack.get("mappings", []):
        if mapping.get("review_status") == "accepted" and not mapping.get("reviewed_by"):
            errors.append(f"compliance mapping {mapping['id']} is accepted without reviewed_by")
        key = (compliance_mapping_pack.get("ruleset"), mapping.get("row_id"))
        if key not in ruleset_rows:
            errors.append(f"compliance mapping {mapping['id']} references unknown ruleset row {key}")
        for fr_id in mapping.get("fr_refs", []):
            if fr_id not in fr_set:
                errors.append(f"compliance mapping {mapping['id']} references unknown FR {fr_id}")
        for tbt_id in mapping.get("tbt_refs", []):
            if tbt_id not in tbt_set:
                errors.append(f"compliance mapping {mapping['id']} references unknown TBT {tbt_id}")

    for fr in fr_catalog.get("frs", []):
        for row in fr.get("satisfies", []):
            key = (row.get("ruleset"), row.get("row"))
            if key not in ruleset_rows:
                errors.append(f"FR {fr['id']} satisfies unknown ruleset row {key}")

    for tbt in fr_catalog.get("tbts", []):
        for fr_id in tbt.get("proves", []):
            if fr_id not in fr_set:
                errors.append(f"TBT {tbt['id']} proves unknown FR {fr_id}")

    for evidence in evidence_bundle.get("evidence", []):
        tbt_id = evidence.get("produced_by")
        if tbt_id not in tbt_set:
            errors.append(f"evidence {evidence['id']} produced_by unknown TBT {tbt_id}")
        if evidence.get("type") in {"document", "screenshot", "manual_note"}:
            if not evidence.get("reviewer"):
                errors.append(f"manual evidence {evidence['id']} is missing reviewer")
            if not evidence.get("source_locator"):
                errors.append(f"manual evidence {evidence['id']} is missing source_locator")

    for process in assurance_framework.get("processes", []):
        for gate in process.get("gates", []):
            for role_req in gate.get("required_roles", []):
                role_id = role_req.get("role")
                if role_id not in role_set:
                    errors.append(f"gate {gate['id']} references unknown role {role_id}")
            for criterion in gate.get("criteria", []):
                for requirement in criterion.get("requirements", []):
                    if requirement.get("type") == "ruleset_row":
                        key = (requirement.get("ruleset"), requirement.get("row"))
                        if key not in ruleset_rows:
                            errors.append(
                                f"criterion {criterion['id']} references unknown ruleset row {key}"
                            )

    for mapping in assurance_instance.get("criterion_mappings", []):
        criterion = mapping.get("criterion")
        if criterion not in criterion_set:
            errors.append(f"assurance mapping references unknown criterion {criterion}")
        for requirement in mapping.get("requirements", []):
            req_type = requirement.get("type")
            ref = requirement.get("ref")
            if req_type == "fr" and ref not in fr_set:
                errors.append(f"assurance mapping references unknown FR {ref}")
            elif req_type == "tbt" and ref not in tbt_set:
                errors.append(f"assurance mapping references unknown TBT {ref}")
            elif req_type == "evidence" and ref not in evidence_set:
                errors.append(f"assurance mapping references unknown evidence {ref}")
            elif req_type == "manual_artifact":
                evidence_ref = requirement.get("evidence")
                if evidence_ref and evidence_ref not in evidence_set:
                    errors.append(f"manual artifact {ref} references unknown evidence {evidence_ref}")
            elif req_type == "ruleset_row":
                key = (requirement.get("ruleset"), requirement.get("row"))
                if key not in ruleset_rows:
                    errors.append(f"assurance mapping references unknown ruleset row {key}")

    for assignment in assurance_instance.get("role_assignments", []):
        if assignment.get("gate") not in gate_set:
            errors.append(f"role assignment references unknown gate {assignment.get('gate')}")
        if assignment.get("role") not in role_set:
            errors.append(f"role assignment references unknown role {assignment.get('role')}")

    target_sets = {
        "fr": fr_set,
        "tbt": tbt_set,
        "evidence": evidence_set,
        "criterion": criterion_set,
        "gate": gate_set,
        "role": role_set,
        "waiver": set(waiver_ids),
    }
    for collection_name, collection in (
        ("waiver", assurance_instance.get("waivers", [])),
        ("compensating control", assurance_instance.get("compensating_controls", [])),
    ):
        for item in collection:
            target_ref = item.get("target_ref") or {}
            target_type = target_ref.get("type")
            target_id = target_ref.get("ref")
            if target_type == "ruleset_row":
                key = (target_ref.get("ruleset"), target_ref.get("row"))
                if key not in ruleset_rows:
                    errors.append(f"{collection_name} {item.get('id')} targets unknown ruleset row {key}")
            elif target_type in target_sets and target_id not in target_sets[target_type]:
                errors.append(f"{collection_name} {item.get('id')} targets unknown {target_type} {target_id}")

    for entry in assurance_test_pack.get("tests", []):
        tbt_id = entry.get("tbt")
        if tbt_id and tbt_id not in tbt_set:
            errors.append(f"test-pack entry {entry['pack_id']} references unknown TBT {tbt_id}")
        for fr_id in entry.get("frs", []):
            if fr_id not in fr_set:
                errors.append(f"test-pack entry {entry['pack_id']} references unknown FR {fr_id}")
        for row in entry.get("ruleset_rows", []):
            key = (row.get("ruleset"), row.get("row"))
            if key not in ruleset_rows:
                errors.append(f"test-pack entry {entry['pack_id']} references unknown ruleset row {key}")
        for gate_id in entry.get("assurance_gates", []):
            if gate_id not in gate_set:
                errors.append(f"test-pack entry {entry['pack_id']} references unknown gate {gate_id}")

    graph = dashboard_payload.get("graph", {})
    graph_node_ids = [node["id"] for node in graph.get("nodes", [])]
    graph_node_set = set(graph_node_ids)
    require_unique(graph_node_ids, "dashboard graph node id", errors)
    for edge in graph.get("edges", []):
        if edge.get("source") not in graph_node_set:
            errors.append(f"dashboard edge source is unknown: {edge.get('source')}")
        if edge.get("target") not in graph_node_set:
            errors.append(f"dashboard edge target is unknown: {edge.get('target')}")

    known_refs = fr_set | tbt_set | evidence_set | gate_set
    for deficiency in agent_prompt_plan.get("deficiencies", []):
        affected = deficiency.get("affected", {})
        for fr_id in affected.get("frs", []):
            if fr_id not in fr_set:
                errors.append(f"deficiency {deficiency['id']} references unknown FR {fr_id}")
        for tbt_id in affected.get("tbts", []):
            if tbt_id not in tbt_set:
                errors.append(f"deficiency {deficiency['id']} references unknown TBT {tbt_id}")
        for gate_id in affected.get("gates", []):
            if gate_id not in gate_set:
                errors.append(f"deficiency {deficiency['id']} references unknown gate {gate_id}")
        for row in affected.get("ruleset_rows", []):
            key = (row.get("ruleset"), row.get("row"))
            if key not in ruleset_rows:
                errors.append(f"deficiency {deficiency['id']} references unknown ruleset row {key}")
    for recommendation in (
        agent_prompt_plan.get("fix_recommendations", [])
        + agent_prompt_plan.get("assurance_recommendations", [])
    ):
        affected = recommendation.get("affected", {})
        for values in affected.values():
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, str) and value.startswith(("FR-", "TBT-", "EVD-", "G")):
                        if value not in known_refs:
                            errors.append(
                                f"recommendation {recommendation['id']} references unknown id {value}"
                            )

    for update in config_update_proposal.get("fr_catalog_updates", []):
        fr_id = update.get("fr_id")
        tbt_id = update.get("tbt_id")
        operation = update.get("operation")
        if operation in {"update_fr", "deprecate_fr", "add_tbt", "update_tbt", "deprecate_tbt"} and fr_id not in fr_set:
            errors.append(f"config proposal references unknown FR {fr_id}")
        if operation in {"update_tbt", "deprecate_tbt"} and tbt_id not in tbt_set:
            errors.append(f"config proposal references unknown TBT {tbt_id}")
        if update.get("review_status") not in {"proposed", "needs_review"}:
            errors.append(f"config proposal update for {fr_id} must remain review-gated")

    for update in config_update_proposal.get("compliance_mapping_pack_updates", []):
        key = (update.get("ruleset"), update.get("row_id"))
        if key not in ruleset_rows:
            errors.append(f"config proposal compliance update references unknown ruleset row {key}")
        for fr_id in update.get("fr_refs", []):
            if fr_id not in fr_set:
                errors.append(f"config proposal compliance update references unknown FR {fr_id}")
        for tbt_id in update.get("tbt_refs", []):
            if tbt_id not in tbt_set:
                errors.append(f"config proposal compliance update references unknown TBT {tbt_id}")

    framework_ids = role_set | gate_set | criterion_set | {process.get("id") for process in assurance_framework.get("processes", []) if process.get("id")}
    for update in config_update_proposal.get("assurance_framework_or_instance_updates", []):
        target = update.get("target", {})
        target_kind = target.get("kind")
        target_id = target.get("id")
        if target_kind in {"process", "gate", "criterion", "role"} and target_id not in framework_ids:
            errors.append(f"config proposal assurance update references unknown {target_kind} {target_id}")
        if target_kind == "fr" and target_id not in fr_set:
            errors.append(f"config proposal assurance update references unknown FR {target_id}")
        if target_kind == "tbt" and target_id not in tbt_set:
            errors.append(f"config proposal assurance update references unknown TBT {target_id}")

    for update in config_update_proposal.get("manual_evidence_updates", []):
        target = update.get("target", {})
        target_kind = target.get("kind")
        target_id = target.get("id")
        if target_kind == "fr" and target_id not in fr_set:
            errors.append(f"config proposal manual evidence update references unknown FR {target_id}")
        if target_kind == "tbt" and target_id not in tbt_set:
            errors.append(f"config proposal manual evidence update references unknown TBT {target_id}")
        if target_kind in {"gate", "criterion", "role"} and target_id not in framework_ids:
            errors.append(f"config proposal manual evidence update references unknown {target_kind} {target_id}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("OK target schema fixtures")
    print(f"  FRs: {len(fr_set)}")
    print(f"  TBTs: {len(tbt_set)}")
    print(f"  Evidence: {len(evidence_set)}")
    print(f"  Ruleset rows: {len(ruleset_rows)}")
    print(f"  Scanner rules: {len(scanner_rule_ids)}")
    print(f"  Scanner compliance mappings: {len(scanner_compliance_mapping_pack.get('mappings') or [])}")
    print(f"  Compliance mappings: {len(compliance_mapping_pack.get('mappings') or [])}")
    print(f"  Blueprint compliance mappings: {len(blueprint_compliance_mapping_pack.get('mappings') or [])}")
    print(f"  Gates: {len(gate_set)}")
    print(f"  Criteria: {len(criterion_set)}")
    print(f"  Test-pack entries: {len(assurance_test_pack.get('tests') or [])}")
    proposal_update_count = sum(
        len(config_update_proposal.get(section) or [])
        for section in (
            "fr_catalog_updates",
            "compliance_mapping_pack_updates",
            "assurance_framework_or_instance_updates",
            "manual_evidence_updates",
        )
    )
    print(f"  Config proposal updates: {proposal_update_count}")
    print(f"  Glossary terms: {len(glossary_term_set)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
