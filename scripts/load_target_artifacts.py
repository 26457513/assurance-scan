#!/usr/bin/env python3
"""Load and validate target assurance JSON artifacts.

These loaders are intentionally dependency-free for normal use. If the optional
``jsonschema`` package is installed, the matching schema is also applied.
Semantic checks that span arrays, such as duplicate IDs and dangling references
inside an artifact, are always performed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from artifact_hashing import canonical_json_sha256
from graph_vocabulary import GRAPH_EDGE_TYPES, GRAPH_NODE_TYPES, GRAPH_RESPONSIBILITIES

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "data" / "schemas"

SCHEMA_BY_KIND = {
    "ruleset": "ruleset.schema.json",
    "authority_source_registry": "authority-source-registry.schema.json",
    "compliance_regime": "compliance-regime.schema.json",
    "scanner_rules": "scanner-rules.schema.json",
    "scanner_compliance_mapping_pack": "scanner-compliance-mapping-pack.schema.json",
    "compliance_mapping_pack": "compliance-mapping-pack.schema.json",
    "blueprint_compliance_mapping_pack": "blueprint-compliance-mapping-pack.schema.json",
    "evidence_bundle": "evidence-bundle.schema.json",
    "assurance_framework": "assurance-framework.schema.json",
    "assurance_instance": "assurance-instance.schema.json",
    "assurance_claim": "assurance-claim.schema.json",
    "assurance_proof_bundle": "assurance-proof-bundle.schema.json",
    "assurance_test_pack": "assurance-test-pack.schema.json",
    "dashboard_payload": "dashboard-payload.schema.json",
    "graph_manifest": "graph-manifest.schema.json",
    "project_fr_board_state": "project-fr-board-state.schema.json",
    "agent_prompt_plan": "agent-prompt-plan.schema.json",
    "config_update_proposal": "config-update-proposal.schema.json",
    "glossary": "glossary.schema.json",
    "project_intake": "project-intake.schema.json",
    "project_config_selection": "project-config-selection.schema.json",
    "project_design_questionnaire": "project-design-questionnaire.schema.json",
    "project_design_answers": "project-design-answers.schema.json",
    "blueprint_selection_proposal": "blueprint-selection-proposal.schema.json",
    "blueprint_decision_log": "blueprint-decision-log.schema.json",
    "project_specific_requirements": "project-specific-requirements.schema.json",
    "repository_analysis_summary": "repository-analysis-summary.schema.json",
    "existing_evidence_mapping_proposal": "existing-evidence-mapping-proposal.schema.json",
    "resolved_project_planning_contract": "resolved-project-planning-contract.schema.json",
    "project_assurance_contract": "project-assurance-contract.schema.json",
    "project_design_document_manifest": "project-design-document-manifest.schema.json",
    "code_studio_handoff_pack": "code-studio-handoff-pack.schema.json",
    "code_generator_handoff_pack": "code-generator-handoff-pack.schema.json",
}

class TargetArtifactError(Exception):
    """Raised when a target artifact is invalid."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(self._format())

    def _format(self) -> str:
        return "Target artifact validation failed:\n" + "\n".join(f"  - {e}" for e in self.errors)


class TargetArtifact:
    """Validated target artifact with small convenience indexes."""

    def __init__(self, kind: str, path: Path, raw: dict[str, Any], warnings: list[str] | None = None) -> None:
        self.kind = kind
        self.path = path
        self.raw = raw
        self.warnings = warnings or []

    @property
    def ids(self) -> set[str]:
        if self.kind == "ruleset":
            return {row["id"] for row in self.raw.get("rows", []) if row.get("id")}
        if self.kind == "evidence_bundle":
            return {ev["id"] for ev in self.raw.get("evidence", []) if ev.get("id")}
        if self.kind == "assurance_framework":
            return _framework_ids(self.raw)
        return set()


def load_target_artifact(path: Path, kind: str, *, strict: bool = False) -> TargetArtifact:
    if kind not in SCHEMA_BY_KIND:
        raise TargetArtifactError([f"Unknown artifact kind '{kind}'. Expected one of {sorted(SCHEMA_BY_KIND)}"])
    if not path.exists():
        raise TargetArtifactError([f"Artifact file not found: {path}"])

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise TargetArtifactError([f"Invalid JSON: {exc}"]) from exc
    if not isinstance(raw, dict):
        raise TargetArtifactError(["Artifact root must be a JSON object"])

    errors = _validate_schema(raw, kind)
    errors.extend(_required_target_shape(raw, kind))
    warnings = _semantic_checks(raw, kind)
    if strict:
        errors.extend(warnings)
    if errors:
        raise TargetArtifactError(errors)
    return TargetArtifact(kind=kind, path=path, raw=raw, warnings=warnings)


def load_ruleset(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "ruleset", strict=strict)


def load_authority_source_registry(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "authority_source_registry", strict=strict)


def load_scanner_rules(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "scanner_rules", strict=strict)


def load_scanner_compliance_mapping_pack(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "scanner_compliance_mapping_pack", strict=strict)


def load_compliance_mapping_pack(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "compliance_mapping_pack", strict=strict)


def load_blueprint_compliance_mapping_pack(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "blueprint_compliance_mapping_pack", strict=strict)


def load_evidence_bundle(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "evidence_bundle", strict=strict)


def load_assurance_framework(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "assurance_framework", strict=strict)


def load_assurance_instance(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "assurance_instance", strict=strict)


def load_assurance_test_pack(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "assurance_test_pack", strict=strict)


def load_config_update_proposal(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "config_update_proposal", strict=strict)


def load_project_fr_board_state(path: Path, *, strict: bool = False) -> TargetArtifact:
    return load_target_artifact(path, "project_fr_board_state", strict=strict)


def validate_assurance_instance_against_framework(instance: dict[str, Any], framework: dict[str, Any]) -> list[str]:
    """Return cross-reference errors between a project instance and framework."""
    role_ids = {role.get("id") for role in framework.get("roles") or [] if role.get("id")}
    gate_ids: set[str] = set()
    criterion_ids: set[str] = set()
    for process in framework.get("processes") or []:
        for gate in process.get("gates") or []:
            if gate.get("id"):
                gate_ids.add(gate["id"])
            for criterion in gate.get("criteria") or []:
                if criterion.get("id"):
                    criterion_ids.add(criterion["id"])

    errors: list[str] = []
    for mapping in instance.get("criterion_mappings") or []:
        criterion = mapping.get("criterion")
        if criterion and criterion not in criterion_ids:
            errors.append(f"Assurance instance criterion mapping references unknown criterion '{criterion}'")
    for assignment in instance.get("role_assignments") or []:
        gate = assignment.get("gate")
        role = assignment.get("role")
        if gate and gate not in gate_ids:
            errors.append(f"Assurance instance role assignment references unknown gate '{gate}'")
        if role and role not in role_ids:
            errors.append(f"Assurance instance role assignment references unknown role '{role}'")
    for decision in instance.get("decisions") or []:
        gate = decision.get("gate")
        if gate and gate not in gate_ids:
            errors.append(f"Assurance instance decision references unknown gate '{gate}'")
    return errors


def _validate_schema(raw: dict[str, Any], kind: str) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []

    schema_path = SCHEMA_DIR / SCHEMA_BY_KIND[kind]
    if not schema_path.exists():
        return [f"Schema file not found: {schema_path}"]
    schema = json.loads(schema_path.read_text())
    validator_kwargs: dict[str, Any] = {}
    try:
        from referencing import Registry, Resource  # type: ignore

        resources = []
        for path in SCHEMA_DIR.glob("*.schema.json"):
            loaded = json.loads(path.read_text())
            schema_id = loaded.get("$id")
            if schema_id:
                resources.append((schema_id, Resource.from_contents(loaded)))
        validator_kwargs["registry"] = Registry().with_resources(resources)
    except Exception:
        validator_kwargs = {}
    validator = jsonschema.Draft202012Validator(schema, **validator_kwargs)
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    ]


def _required_target_shape(raw: dict[str, Any], kind: str) -> list[str]:
    required_by_kind = {
        "ruleset": ["schema_version", "ruleset", "version", "title", "source", "rows"],
        "authority_source_registry": ["schema_version", "sources"],
        "compliance_regime": ["schema_version", "regime", "version", "title", "ruleset_ref", "source", "families"],
        "scanner_rules": ["schema_version", "scanner", "rules"],
        "scanner_compliance_mapping_pack": ["schema_version", "pack", "scanner", "compliance", "mappings"],
        "compliance_mapping_pack": ["schema_version", "pack", "ruleset", "ruleset_version", "mappings"],
        "blueprint_compliance_mapping_pack": ["schema_version", "pack", "blueprint", "compliance", "mappings"],
        "evidence_bundle": ["schema_version", "project", "evidence"],
        "assurance_framework": ["schema_version", "assurance_framework", "version", "title", "roles", "processes"],
        "assurance_instance": ["schema_version", "project", "assurance_framework"],
        "assurance_claim": ["schema_version", "mode", "claim_type", "target", "claim_result", "graph_manifest", "public_inputs", "evaluation"],
        "assurance_proof_bundle": ["schema_version", "mode", "bundle_type", "claim", "claim_hash", "public_commitments", "evidence_commitments", "openings"],
        "assurance_test_pack": ["schema_version", "name", "mode", "generated_at", "tests"],
        "dashboard_payload": ["schema_version", "project", "generated_at", "inputs", "summary", "graph"],
        "graph_manifest": ["schema_version", "mode", "project", "generated_at", "graph", "artifacts", "commitments", "supported_claims"],
        "project_fr_board_state": ["schema_version", "mode", "project", "run_id", "generated_at", "cards"],
        "agent_prompt_plan": ["schema_version", "project", "mode", "deficiencies"],
        "config_update_proposal": ["schema_version", "mode", "project", "run_id", "source_inputs"],
        "glossary": ["schema_version", "terms"],
        "project_intake": ["schema_version", "id", "status", "project", "mode", "intent"],
        "project_config_selection": ["schema_version", "id", "status", "project", "selections"],
        "project_design_questionnaire": ["schema_version", "id", "status", "project", "questions"],
        "project_design_answers": ["schema_version", "id", "status", "project", "questionnaire", "answers"],
        "blueprint_selection_proposal": ["schema_version", "id", "status", "project", "source_blueprints", "candidates"],
        "blueprint_decision_log": ["schema_version", "id", "project", "proposal", "decisions"],
        "project_specific_requirements": ["schema_version", "id", "status", "project", "requirements"],
        "repository_analysis_summary": ["schema_version", "id", "project", "source_repo", "findings"],
        "existing_evidence_mapping_proposal": ["schema_version", "id", "status", "project", "proposals"],
        "resolved_project_planning_contract": [
            "schema_version",
            "id",
            "status",
            "project",
            "source_artifacts",
            "sections",
            "section_hashes",
            "contract_hash",
        ],
        "project_assurance_contract": [
            "schema_version",
            "id",
            "project",
            "derived_from_contract",
            "artifacts",
            "content_hash",
        ],
        "project_design_document_manifest": [
            "schema_version",
            "id",
            "project",
            "source_contract",
            "document_path",
            "document_hash",
        ],
        "code_studio_handoff_pack": [
            "schema_version",
            "id",
            "project",
            "source_contract",
            "source_contract_hash",
            "context",
        ],
        "code_generator_handoff_pack": [
            "schema_version",
            "id",
            "project",
            "source_contract",
            "source_contract_hash",
            "tasks",
            "gates",
        ],
    }
    errors: list[str] = []
    for key in required_by_kind[kind]:
        if key not in raw:
            errors.append(f"Missing required field '{key}'")
    if raw.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    return errors


def _semantic_checks(raw: dict[str, Any], kind: str) -> list[str]:
    errors = _check_content_hash(raw, kind)
    if kind == "ruleset":
        errors.extend(_check_unique(raw.get("rows") or [], "ruleset row"))
        source = raw.get("source") or {}
        raw_artifacts = source.get("raw_artifacts") or []
        transform = source.get("transform") or {}
        if not raw_artifacts:
            errors.append(f"Ruleset {raw.get('ruleset')} {raw.get('version')}: source.raw_artifacts is required")
        if not transform:
            errors.append(f"Ruleset {raw.get('ruleset')} {raw.get('version')}: source.transform is required")
        return errors
    if kind == "authority_source_registry":
        entries = raw.get("sources") or []
        seen: set[str] = set()
        for entry in entries:
            entry_id = entry.get("id")
            if entry_id in seen:
                errors.append(f"Authority source duplicate id {entry_id}")
            seen.add(entry_id)
        return errors
    if kind == "scanner_rules":
        errors.extend(_check_unique(raw.get("rules") or [], "scanner rule"))
        return errors
    if kind == "scanner_compliance_mapping_pack":
        errors.extend(_check_unique(raw.get("mappings") or [], "scanner compliance mapping"))
        for mapping in raw.get("mappings") or []:
            if mapping.get("review_status") == "accepted" and not mapping.get("reviewed_by"):
                errors.append(f"Scanner compliance mapping {mapping.get('id')}: accepted mappings require reviewed_by")
            targets = mapping.get("targets") or {}
            level = mapping.get("mapping_level")
            if level == "compliance_row" and not targets.get("compliance_rows"):
                errors.append(f"Scanner compliance mapping {mapping.get('id')}: compliance_row mappings require compliance_rows")
            if level == "compliance_domain" and not targets.get("compliance_domains"):
                errors.append(f"Scanner compliance mapping {mapping.get('id')}: compliance_domain mappings require compliance_domains")
            if level == "general_finding" and (targets.get("compliance_rows") or targets.get("compliance_domains")):
                errors.append(f"Scanner compliance mapping {mapping.get('id')}: general_finding mappings cannot declare compliance targets")
        return errors
    if kind == "compliance_mapping_pack":
        errors.extend(_check_unique(raw.get("mappings") or [], "compliance mapping"))
        for mapping in raw.get("mappings") or []:
            if mapping.get("review_status") == "accepted" and not mapping.get("reviewed_by"):
                errors.append(f"Compliance mapping {mapping.get('id')}: accepted mappings require reviewed_by")
        return errors
    if kind == "blueprint_compliance_mapping_pack":
        errors.extend(_check_unique(raw.get("mappings") or [], "blueprint compliance mapping"))
        for mapping in raw.get("mappings") or []:
            if mapping.get("review_status") == "accepted" and not mapping.get("reviewed_by"):
                errors.append(f"Blueprint compliance mapping {mapping.get('id')}: accepted mappings require reviewed_by")
            refs = mapping.get("blueprint_refs") or {}
            if not refs.get("fr_refs") and not refs.get("tbt_refs"):
                errors.append(f"Blueprint compliance mapping {mapping.get('id')}: at least one blueprint FR or TBT ref is required")
            targets = mapping.get("targets") or {}
            level = mapping.get("mapping_level")
            if level == "compliance_row" and not targets.get("compliance_rows"):
                errors.append(f"Blueprint compliance mapping {mapping.get('id')}: compliance_row mappings require compliance_rows")
            if level == "compliance_domain" and not targets.get("compliance_domains"):
                errors.append(f"Blueprint compliance mapping {mapping.get('id')}: compliance_domain mappings require compliance_domains")
        return errors
    if kind == "evidence_bundle":
        errors.extend(_check_unique(raw.get("evidence") or [], "evidence"))
        for ev in raw.get("evidence") or []:
            if not ev.get("produced_by", "").startswith("TBT-"):
                errors.append(f"Evidence {ev.get('id')}: produced_by must reference a TBT")
        return errors
    if kind == "assurance_framework":
        errors.extend(_check_assurance_framework(raw))
        return errors
    if kind == "assurance_instance":
        errors.extend(_check_unique(raw.get("waivers") or [], "waiver"))
        errors.extend(_check_unique(raw.get("compensating_controls") or [], "compensating control"))
        errors.extend(_check_unique(raw.get("decisions") or [], "decision"))
        return errors
    if kind == "assurance_proof_bundle":
        errors.extend(_check_assurance_proof_bundle(raw))
        return errors
    if kind == "assurance_test_pack":
        errors.extend(_check_unique(raw.get("tests") or [], "test-pack entry"))
        for entry in raw.get("tests") or []:
            tbt = entry.get("tbt")
            if tbt and not str(tbt).startswith("TBT-"):
                errors.append(f"Test-pack entry {entry.get('pack_id')}: tbt must reference a TBT")
        return errors
    if kind == "config_update_proposal":
        errors.extend(_check_config_update_proposal(raw))
        return errors
    if kind == "dashboard_payload":
        errors.extend(_check_dashboard_payload(raw))
        return errors
    if kind == "graph_manifest":
        errors.extend(_check_graph_manifest(raw))
        return errors
    if kind == "project_fr_board_state":
        errors.extend(_check_project_fr_board_state(raw))
        return errors
    if kind == "glossary":
        errors.extend(_check_unique(raw.get("terms") or [], "glossary term"))
        return errors
    if kind == "resolved_project_planning_contract":
        errors.extend(_check_resolved_project_planning_contract(raw))
        return errors
    return errors


def _check_content_hash(raw: dict[str, Any], kind: str) -> list[str]:
    observed = raw.get("content_hash")
    if not observed:
        return []
    unhashed = dict(raw)
    unhashed.pop("content_hash", None)
    expected = canonical_json_sha256(unhashed)
    if observed != expected:
        return [f"{kind}: content_hash must match canonical artifact content"]
    return []


def _check_resolved_project_planning_contract(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    sections = raw.get("sections") or {}
    section_hashes = raw.get("section_hashes") or {}
    for key, value in sections.items():
        expected = canonical_json_sha256(value)
        if section_hashes.get(key) != expected:
            errors.append(f"Resolved planning contract section_hashes.{key} must match sections.{key}")
    unhashed = dict(raw)
    unhashed.pop("contract_hash", None)
    unhashed.pop("content_hash", None)
    expected_contract_hash = canonical_json_sha256(unhashed)
    if raw.get("contract_hash") != expected_contract_hash:
        errors.append("Resolved planning contract contract_hash must match canonical contract content")
    return errors


def _check_project_fr_board_state(raw: dict[str, Any]) -> list[str]:
    errors = _check_unique(raw.get("cards") or [], "project FR board card")
    if raw.get("mode") != "project_fr_board_state":
        errors.append("Project FR board state mode must be project_fr_board_state")
    for card in raw.get("cards") or []:
        card_id = card.get("id") or "<unknown>"
        lane = card.get("lane")
        decision = card.get("decision", "")
        if lane == "import" and decision not in {"approve_to_run", ""}:
            errors.append(f"Project FR board card {card_id}: import lane requires approve_to_run or no decision")
        if lane == "review" and decision == "approve_to_run":
            errors.append(f"Project FR board card {card_id}: approve_to_run belongs in the import lane")
        if decision in {"accept_recommendation", "approve_for_implementation", "approve_to_run"} and not card.get("reviewer_note"):
            errors.append(f"Project FR board card {card_id}: accepted/approved decisions require reviewer_note")
    return errors


def _check_graph_manifest(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    graph = raw.get("graph") or {}
    commitments = raw.get("commitments") or {}
    accepted_config = raw.get("accepted_config") or {}
    planning_artifacts = raw.get("planning_artifacts") or {}
    claim_readiness = raw.get("claim_readiness") or {}
    if raw.get("mode") != "graph_proof_manifest":
        errors.append("Graph manifest mode must be graph_proof_manifest")
    root_hash = graph.get("root_hash")
    if root_hash and commitments.get("graph_root_hash") and commitments.get("graph_root_hash") != root_hash:
        errors.append("Graph manifest graph.root_hash must match commitments.graph_root_hash")
    config_commitments = accepted_config.get("commitments") or []
    if accepted_config.get("commitment_count") != len(config_commitments):
        errors.append("Graph manifest accepted_config.commitment_count must match commitments length")
    accepted_config_hash = commitments.get("accepted_config_hash")
    if accepted_config_hash and accepted_config_hash != canonical_json_sha256(accepted_config):
        errors.append("Graph manifest commitments.accepted_config_hash must match accepted_config")
    planning_commitments = planning_artifacts.get("commitments") or []
    if planning_artifacts and planning_artifacts.get("commitment_count") != len(planning_commitments):
        errors.append("Graph manifest planning_artifacts.commitment_count must match commitments length")
    planning_artifacts_hash = commitments.get("planning_artifacts_hash")
    if planning_artifacts_hash and planning_artifacts_hash != canonical_json_sha256(planning_artifacts):
        errors.append("Graph manifest commitments.planning_artifacts_hash must match planning_artifacts")
    supported_claims = raw.get("supported_claims") or []
    if claim_readiness and supported_claims != claim_readiness.get("supported"):
        errors.append("Graph manifest supported_claims must match claim_readiness.supported")
    for commitment in [*config_commitments, *planning_commitments]:
        if (commitment.get("freeze") or {}).get("mode") != "content_addressed":
            errors.append(f"Graph manifest config {commitment.get('id')}: freeze.mode must be content_addressed")
        if (commitment.get("freeze") or {}).get("immutable") is not True:
            errors.append(f"Graph manifest config {commitment.get('id')}: freeze.immutable must be true")
        if commitment.get("sha256") and not str(commitment["sha256"]).startswith("sha256:"):
            errors.append(f"Graph manifest config {commitment.get('id')}: sha256 must use sha256: prefix")
        summary = commitment.get("review_summary") or {}
        if summary:
            errors.extend(_check_review_summary(summary, f"Graph manifest config {commitment.get('id')}"))
    for bucket_name in ("report", "config"):
        for artifact in ((raw.get("artifacts") or {}).get(bucket_name) or []):
            if artifact.get("sha256") and not str(artifact["sha256"]).startswith("sha256:"):
                errors.append(f"Graph manifest {bucket_name} artifact {artifact.get('path')}: sha256 must use sha256: prefix")
    return errors


def _check_assurance_proof_bundle(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if raw.get("mode") != "assurance_proof_bundle":
        errors.append("Proof bundle mode must be assurance_proof_bundle")
    if raw.get("bundle_type") != "selective_disclosure_v1":
        errors.append("Proof bundle bundle_type must be selective_disclosure_v1")
    claim = raw.get("claim") or {}
    if raw.get("claim_hash") != canonical_json_sha256(claim):
        errors.append("Proof bundle claim_hash must match embedded claim")
    public = raw.get("public_commitments") or {}
    graph_manifest = claim.get("graph_manifest") or {}
    if public.get("graph_manifest_hash") != graph_manifest.get("sha256"):
        errors.append("Proof bundle public_commitments.graph_manifest_hash must match embedded claim")
    if public.get("graph_root_hash") != graph_manifest.get("graph_root_hash"):
        errors.append("Proof bundle public_commitments.graph_root_hash must match embedded claim")
    if public.get("accepted_config_hash") != graph_manifest.get("accepted_config_hash"):
        errors.append("Proof bundle public_commitments.accepted_config_hash must match embedded claim")
    public_inputs = claim.get("public_inputs") or {}
    for key in ("evidence_bundle_hash", "evidence_manifest_hash", "dashboard_payload_hash"):
        if public.get(key) != public_inputs.get(key):
            errors.append(f"Proof bundle public_commitments.{key} must match embedded claim public_inputs")
    return errors


def _check_review_summary(summary: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    review_counts = summary.get("review_status_counts") or {}
    approval_counts = summary.get("approval_status_counts") or {}
    if review_counts and summary.get("reviewed_item_count") != sum(review_counts.values()):
        errors.append(f"{label}: reviewed_item_count must equal review_status_counts total")
    if approval_counts and summary.get("approval_item_count") != sum(approval_counts.values()):
        errors.append(f"{label}: approval_item_count must equal approval_status_counts total")
    signature_refs = summary.get("signature_refs") or []
    if signature_refs and summary.get("signed_item_count") != len(signature_refs):
        errors.append(f"{label}: signed_item_count must equal signature_refs length")
    for key in ("reviewers", "approvers", "deciders", "signature_refs"):
        values = summary.get(key) or []
        if values != sorted(set(values)):
            errors.append(f"{label}: {key} must be unique and sorted")
    return errors


def _check_unique(items: list[dict[str, Any]], label: str) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for item in items:
        item_id = item.get("id")
        if not item_id:
            continue
        if item_id in seen:
            errors.append(f"Duplicate {label} id '{item_id}'")
        seen.add(item_id)
    return errors


def _check_dashboard_payload(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    graph = raw.get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    node_ids = set()
    for node in nodes:
        node_id = node.get("id")
        node_type = node.get("type")
        if node_id:
            if node_id in node_ids:
                errors.append(f"Dashboard graph duplicate node id: {node_id}")
            node_ids.add(node_id)
        if node_type not in GRAPH_NODE_TYPES:
            errors.append(f"Dashboard graph node {node_id or '<missing id>'}: unknown type {node_type!r}")
    edge_keys = set()
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        edge_type = edge.get("type")
        edge_key = (source, target, edge_type)
        if edge_key in edge_keys:
            errors.append(f"Dashboard graph duplicate edge: {source}->{target}:{edge_type}")
        edge_keys.add(edge_key)
        if source not in node_ids:
            errors.append(f"Dashboard graph edge references unknown source node {source!r}")
        if target not in node_ids:
            errors.append(f"Dashboard graph edge references unknown target node {target!r}")
        if edge_type not in GRAPH_EDGE_TYPES:
            errors.append(f"Dashboard graph edge {source}->{target}: unknown type {edge_type!r}")
        responsibility = edge.get("responsibility")
        if responsibility is not None and responsibility not in GRAPH_RESPONSIBILITIES:
            errors.append(
                f"Dashboard graph edge {source}->{target}: unknown responsibility {responsibility!r}"
            )
    return errors


def _framework_ids(raw: dict[str, Any]) -> set[str]:
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


def _check_assurance_framework(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    role_ids = {role.get("id") for role in raw.get("roles") or [] if role.get("id")}
    errors.extend(_check_unique(raw.get("roles") or [], "role"))
    process_ids: set[str] = set()
    gate_ids: set[str] = set()
    criterion_ids: set[str] = set()

    for process in raw.get("processes") or []:
        process_id = process.get("id")
        if process_id in process_ids:
            errors.append(f"Duplicate process id '{process_id}'")
        process_ids.add(process_id)
        for gate in process.get("gates") or []:
            gate_id = gate.get("id")
            if gate_id in gate_ids:
                errors.append(f"Duplicate gate id '{gate_id}'")
            gate_ids.add(gate_id)
            for required_role in gate.get("required_roles") or []:
                role = required_role.get("role")
                if role and role not in role_ids:
                    errors.append(f"Gate {gate_id}: required role '{role}' is not defined")
            for criterion in gate.get("criteria") or []:
                criterion_id = criterion.get("id")
                if criterion_id in criterion_ids:
                    errors.append(f"Duplicate criterion id '{criterion_id}'")
                criterion_ids.add(criterion_id)
    return errors


def _check_config_update_proposal(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if raw.get("mode") != "config_update_proposal":
        errors.append("mode must be config_update_proposal")

    update_sections = [
        "fr_catalog_updates",
        "compliance_mapping_pack_updates",
        "assurance_framework_or_instance_updates",
        "manual_evidence_updates",
    ]
    total_updates = 0
    for section in update_sections:
        updates = raw.get(section) or []
        if not isinstance(updates, list):
            continue
        total_updates += len(updates)
        for idx, update in enumerate(updates, start=1):
            review_status = update.get("review_status")
            if review_status not in {"proposed", "needs_review"}:
                errors.append(f"{section}[{idx}]: review_status must be proposed or needs_review")
            if not update.get("source_basis"):
                errors.append(f"{section}[{idx}]: source_basis is required")
            if not update.get("rationale"):
                errors.append(f"{section}[{idx}]: rationale is required")
            if not update.get("confidence"):
                errors.append(f"{section}[{idx}]: confidence is required")

    if total_updates == 0 and not raw.get("uncertain_mappings") and not raw.get("review_required"):
        errors.append("proposal must contain at least one update, uncertain mapping, or review item")

    for section in ("fr_catalog_updates", "compliance_mapping_pack_updates"):
        for idx, update in enumerate(raw.get(section) or [], start=1):
            if update.get("evidence") or update.get("observed_evidence") or update.get("result"):
                errors.append(
                    f"{section}[{idx}]: config proposals must not claim observed evidence or test results"
                )

    return errors


def _summarise(artifact: TargetArtifact) -> str:
    raw = artifact.raw
    if artifact.kind == "ruleset":
        return f"{raw.get('ruleset')} {raw.get('version')}: {len(raw.get('rows') or [])} rows"
    if artifact.kind == "compliance_regime":
        return f"{raw.get('regime')} {raw.get('version')}: {len(raw.get('families') or [])} families"
    if artifact.kind == "scanner_rules":
        return f"{raw.get('scanner')}: {len(raw.get('rules') or [])} scanner rules"
    if artifact.kind == "scanner_compliance_mapping_pack":
        compliance = raw.get("compliance") or {}
        return (
            f"{raw.get('scanner')}: {len(raw.get('mappings') or [])} scanner-to-"
            f"{compliance.get('ruleset', 'compliance')} mappings"
        )
    if artifact.kind == "compliance_mapping_pack":
        return f"{raw.get('ruleset')} {raw.get('ruleset_version')}: {len(raw.get('mappings') or [])} compliance mappings"
    if artifact.kind == "blueprint_compliance_mapping_pack":
        blueprint = raw.get("blueprint") or {}
        compliance = raw.get("compliance") or {}
        return (
            f"{blueprint.get('catalog')} {blueprint.get('version')} -> "
            f"{compliance.get('ruleset')} {compliance.get('version')}: "
            f"{len(raw.get('mappings') or [])} blueprint compliance mappings"
        )
    if artifact.kind == "evidence_bundle":
        return f"{raw.get('project')}: {len(raw.get('evidence') or [])} evidence records"
    if artifact.kind == "assurance_framework":
        gates = sum(len(process.get("gates") or []) for process in raw.get("processes") or [])
        criteria = sum(
            len(gate.get("criteria") or [])
            for process in raw.get("processes") or []
            for gate in process.get("gates") or []
        )
        version = raw.get("version") or "unversioned"
        return f"{raw.get('assurance_framework')} {version}: {len(raw.get('roles') or [])} roles, {gates} gates, {criteria} criteria"
    if artifact.kind == "assurance_instance":
        return (
            f"{raw.get('project')} / {raw.get('assurance_framework')}: "
            f"{len(raw.get('criterion_mappings') or [])} criterion mappings, "
            f"{len(raw.get('role_assignments') or [])} role assignments"
        )
    if artifact.kind == "assurance_test_pack":
        return f"{raw.get('name')}: {len(raw.get('tests') or [])} test-pack entries"
    if artifact.kind == "config_update_proposal":
        update_count = sum(
            len(raw.get(section) or [])
            for section in (
                "fr_catalog_updates",
                "compliance_mapping_pack_updates",
                "assurance_framework_or_instance_updates",
                "manual_evidence_updates",
                "native_test_mapping_updates",
            )
        )
        return (
            f"{raw.get('project')} / {raw.get('run_id')}: "
            f"{update_count} proposed updates, "
            f"{len(raw.get('uncertain_mappings') or [])} uncertain mappings"
        )
    return f"{artifact.kind}: valid"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=sorted(SCHEMA_BY_KIND))
    parser.add_argument("path", type=Path)
    parser.add_argument("--strict", action="store_true", help="Treat semantic warnings as errors")
    args = parser.parse_args()

    try:
        artifact = load_target_artifact(args.path, args.kind, strict=args.strict)
    except TargetArtifactError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {args.path.name} — {_summarise(artifact)}")
    if artifact.warnings:
        print(f"\n{len(artifact.warnings)} warning(s):", file=sys.stderr)
        for warning in artifact.warnings:
            print(f"  - {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
