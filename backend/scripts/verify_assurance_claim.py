"""Shared assurance-claim verification helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from artifact_hashing import file_sha256
from assurance_claims import assert_claim_supported, evaluate_claim, load_json
from load_target_artifacts import TargetArtifactError, load_target_artifact


def _claim_result(evaluation: dict[str, Any]) -> str:
    return "satisfied" if evaluation.get("satisfied") else "unsatisfied"


def verify_claim(claim_path: Path, report_dir: Path) -> list[str]:
    errors: list[str] = []
    try:
        artifact = load_target_artifact(claim_path, "assurance_claim", strict=True)
    except TargetArtifactError as exc:
        return exc.errors
    claim = artifact.raw

    manifest_path = report_dir / str((claim.get("graph_manifest") or {}).get("path") or "graph-manifest.json")
    payload_path = report_dir / "dashboard-payload.json"
    if not manifest_path.exists():
        return [f"graph manifest not found: {manifest_path}"]
    if not payload_path.exists():
        return [f"dashboard payload not found: {payload_path}"]

    manifest = load_json(manifest_path)
    payload = load_json(payload_path)
    graph_manifest = claim.get("graph_manifest") or {}
    commitments = manifest.get("commitments") or {}

    expected_manifest_hash = file_sha256(manifest_path, prefixed=True)
    if graph_manifest.get("sha256") != expected_manifest_hash:
        errors.append("claim graph_manifest.sha256 does not match graph-manifest.json")
    if graph_manifest.get("graph_root_hash") != commitments.get("graph_root_hash"):
        errors.append("claim graph_manifest.graph_root_hash does not match manifest commitments")
    if graph_manifest.get("accepted_config_hash") != commitments.get("accepted_config_hash"):
        errors.append("claim graph_manifest.accepted_config_hash does not match manifest commitments")
    if claim.get("public_inputs") != commitments:
        errors.append("claim public_inputs do not match graph manifest commitments")

    claim_type = str(claim.get("claim_type") or "")
    try:
        assert_claim_supported(manifest, claim_type)
    except ValueError as exc:
        errors.append(str(exc))

    evaluation = evaluate_claim(payload.get("graph") or {}, claim_type, str(claim.get("target") or ""))
    if claim.get("claim_result") != _claim_result(evaluation):
        errors.append("claim_result does not match recomputed graph evaluation")
    if (claim.get("evaluation") or {}).get("target_node_id") != evaluation.get("target_node_id"):
        errors.append("evaluation.target_node_id does not match recomputed graph evaluation")
    if (claim.get("evaluation") or {}).get("target_status") != evaluation.get("target_status"):
        errors.append("evaluation.target_status does not match recomputed graph evaluation")
    if (claim.get("evaluation") or {}).get("satisfied") != evaluation.get("satisfied"):
        errors.append("evaluation.satisfied does not match recomputed graph evaluation")
    if sorted((claim.get("evaluation") or {}).get("evidence_refs") or []) != sorted(evaluation.get("evidence_refs") or []):
        errors.append("evaluation.evidence_refs do not match recomputed graph evaluation")
    if sorted((claim.get("evaluation") or {}).get("scanner_blockers") or []) != sorted(evaluation.get("scanner_blockers") or []):
        errors.append("evaluation.scanner_blockers do not match recomputed graph evaluation")
    return errors
