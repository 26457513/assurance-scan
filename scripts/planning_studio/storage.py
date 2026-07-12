"""File-backed Planning Studio artifact storage."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from artifact_hashing import canonical_json_sha256


ARTIFACT_FILES = {
    "project_intake": "intake.json",
    "project_config_selection": "config-selection.json",
    "project_design_questionnaire": "questionnaire.json",
    "project_design_answers": "answers.json",
    "repository_analysis_summary": "repository-analysis.json",
    "existing_evidence_mapping_proposal": "existing-evidence-mapping-proposal.json",
    "blueprint_selection_proposal": "blueprint-proposal.json",
    "blueprint_decision_log": "blueprint-decisions.json",
    "project_specific_requirements": "project-specific-requirements.draft.json",
    "config_update_proposal": "config-update-proposal.json",
    "resolved_project_planning_contract": "resolved-planning-contract.json",
    "project_assurance_contract": "project-assurance-contract.json",
    "project_design_document_manifest": "design-document-manifest.json",
    "code_studio_handoff_pack": "code-studio-handoff.json",
    "code_generator_handoff_pack": "code-generator-handoff.json",
}


def artifact_path(root: Path, kind: str) -> Path:
    if kind not in ARTIFACT_FILES:
        raise KeyError(f"Unknown Planning Studio artifact kind: {kind}")
    return root / ARTIFACT_FILES[kind]


def with_content_hash(payload: dict[str, Any]) -> dict[str, Any]:
    copy = dict(payload)
    copy.pop("content_hash", None)
    payload = dict(payload)
    payload["content_hash"] = canonical_json_sha256(copy)
    return payload


def write_artifact(root: Path, kind: str, payload: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = artifact_path(root, kind)
    path.write_text(json.dumps(with_content_hash(payload), indent=2, sort_keys=False) + "\n")
    return path


def read_artifact(root: Path, kind: str) -> dict[str, Any]:
    path = artifact_path(root, kind)
    return json.loads(path.read_text())

