"""Selective-disclosure assurance proof bundle helpers."""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from artifact_hashing import canonical_json_sha256, ensure_sha256_prefix, file_sha256
from assurance_claims import load_json
from verify_assurance_claim import verify_claim
from load_target_artifacts import TargetArtifactError, load_target_artifact


def _artifact_commitments(record: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for artifact in [record.get("artifact"), *(record.get("raw_artifacts") or [])]:
        if not isinstance(artifact, dict):
            continue
        item = {
            "path": str(artifact.get("path") or ""),
            "sha256": ensure_sha256_prefix(str(artifact.get("sha256") or "")),
        }
        for key in ("bytes", "format", "media_type", "locator"):
            if artifact.get(key) not in (None, ""):
                item[key] = artifact[key]
        if item["path"] and item["sha256"]:
            artifacts.append(item)
    return sorted(artifacts, key=lambda item: (item["path"], item["sha256"]))


def evidence_commitments_for_claim(report_dir: Path, claim: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_bundle = load_json(report_dir / "evidence-bundle.json") if (report_dir / "evidence-bundle.json").exists() else {}
    wanted = set((claim.get("evaluation") or {}).get("evidence_refs") or [])
    commitments: list[dict[str, Any]] = []
    for record in evidence_bundle.get("evidence") or []:
        record_id = str(record.get("id") or "")
        if wanted and record_id not in wanted and str(record.get("produced_by") or "") not in wanted:
            continue
        commitments.append({
            "id": record_id,
            "type": str(record.get("type") or ""),
            "produced_by": str(record.get("produced_by") or ""),
            "result_status": str(record.get("result_status") or ""),
            "record_hash": canonical_json_sha256(record),
            "artifact_hashes": _artifact_commitments(record),
        })
    return sorted(commitments, key=lambda item: item["id"])


def opening_for_path(report_dir: Path, rel_path: str) -> dict[str, Any]:
    path = report_dir / rel_path
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"opening artifact not found: {rel_path}")
    content = path.read_bytes()
    return {
        "path": rel_path,
        "sha256": file_sha256(path, prefixed=True),
        "bytes": len(content),
        "encoding": "base64",
        "media_type": "application/octet-stream",
        "content": base64.b64encode(content).decode("ascii"),
    }


def build_proof_bundle(report_dir: Path, claim_path: Path, openings: list[str] | None = None) -> dict[str, Any]:
    claim_errors = verify_claim(claim_path, report_dir)
    if claim_errors:
        raise ValueError("; ".join(claim_errors))
    claim = load_json(claim_path)
    manifest_path = report_dir / str((claim.get("graph_manifest") or {}).get("path") or "graph-manifest.json")
    manifest = load_json(manifest_path)
    commitments = manifest.get("commitments") or {}
    return {
        "schema_version": 1,
        "mode": "assurance_proof_bundle",
        "bundle_type": "selective_disclosure_v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "claim": claim,
        "claim_hash": canonical_json_sha256(claim),
        "public_commitments": {
            "graph_manifest_hash": file_sha256(manifest_path, prefixed=True),
            "graph_root_hash": commitments.get("graph_root_hash", ""),
            "accepted_config_hash": commitments.get("accepted_config_hash", ""),
            "evidence_bundle_hash": commitments.get("evidence_bundle_hash", ""),
            "evidence_manifest_hash": commitments.get("evidence_manifest_hash", ""),
            "dashboard_payload_hash": commitments.get("dashboard_payload_hash", ""),
        },
        "evidence_commitments": evidence_commitments_for_claim(report_dir, claim),
        "openings": [opening_for_path(report_dir, rel_path) for rel_path in (openings or [])],
    }


def verify_proof_bundle(bundle_path: Path, report_dir: Path | None = None) -> list[str]:
    errors: list[str] = []
    try:
        artifact = load_target_artifact(bundle_path, "assurance_proof_bundle", strict=True)
    except TargetArtifactError as exc:
        return exc.errors
    bundle = artifact.raw
    claim = bundle.get("claim") or {}
    if bundle.get("claim_hash") != canonical_json_sha256(claim):
        errors.append("claim_hash does not match embedded claim")
    public = bundle.get("public_commitments") or {}
    graph_manifest = claim.get("graph_manifest") or {}
    if public.get("graph_manifest_hash") != graph_manifest.get("sha256"):
        errors.append("public_commitments.graph_manifest_hash does not match embedded claim")
    if public.get("graph_root_hash") != graph_manifest.get("graph_root_hash"):
        errors.append("public_commitments.graph_root_hash does not match embedded claim")
    if public.get("accepted_config_hash") != graph_manifest.get("accepted_config_hash"):
        errors.append("public_commitments.accepted_config_hash does not match embedded claim")
    for key in ("evidence_bundle_hash", "evidence_manifest_hash", "dashboard_payload_hash"):
        if public.get(key) != (claim.get("public_inputs") or {}).get(key):
            errors.append(f"public_commitments.{key} does not match embedded claim public_inputs")

    for opening in bundle.get("openings") or []:
        try:
            content = base64.b64decode(str(opening.get("content") or ""), validate=True)
        except Exception:
            errors.append(f"opening {opening.get('path')}: content is not valid base64")
            continue
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if digest != opening.get("sha256"):
            errors.append(f"opening {opening.get('path')}: sha256 does not match content")
        if len(content) != opening.get("bytes"):
            errors.append(f"opening {opening.get('path')}: bytes does not match content length")

    if report_dir:
        # Avoid writing temporary files: perform the report-specific checks inline.
        manifest_path = report_dir / str(graph_manifest.get("path") or "graph-manifest.json")
        if not manifest_path.exists():
            errors.append(f"graph manifest not found: {manifest_path}")
        elif file_sha256(manifest_path, prefixed=True) != graph_manifest.get("sha256"):
            errors.append("embedded claim graph_manifest.sha256 does not match report graph-manifest.json")
        if report_dir and not errors:
            # Rebuild a claim from the report and compare stable fields.
            from assurance_claims import build_claim
            rebuilt = build_claim(report_dir, str(claim.get("claim_type") or ""), str(claim.get("target") or ""))
            for key in ("claim_type", "target", "claim_result", "project", "run_id", "graph_manifest", "public_inputs", "evaluation"):
                if rebuilt.get(key) != claim.get(key):
                    errors.append(f"embedded claim {key} does not match report recomputation")
                    break
            if evidence_commitments_for_claim(report_dir, claim) != bundle.get("evidence_commitments"):
                errors.append("evidence_commitments do not match report evidence-bundle.json")
    return errors


def default_bundle_path(report_dir: Path, claim_path: Path) -> Path:
    return report_dir / "proof-bundles" / f"{claim_path.stem}.proof-bundle.json"
