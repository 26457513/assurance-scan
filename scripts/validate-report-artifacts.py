#!/usr/bin/env python3
"""Validate target-schema artifacts emitted into a scan report directory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from artifact_hashing import file_sha256, report_hash_filename
from assurance_proof_bundles import verify_proof_bundle
from load_target_artifacts import TargetArtifactError, load_target_artifact
from verify_assurance_claim import verify_claim


REPORT_ARTIFACTS = {
    "evidence_bundle": "evidence-bundle.json",
    "agent_prompt_plan": "agent-prompt-plan.json",
    "dashboard_payload": "dashboard-payload.json",
    "graph_manifest": "graph-manifest.json",
}

OPTIONAL_REPORT_ARTIFACTS = {
    "assurance_test_pack": "generated-tests/VG_TEST_FRAMEWORK/manifest.json",
    "config_update_proposal": "fr-config-update-proposal.template.json",
    "project_fr_board_state": "project-fr-board-state.json",
}


def _hash_path(report_dir: Path, rel: str) -> Path:
    return report_dir / "hashes" / report_hash_filename(rel)


def _actual_digest(path: Path) -> str:
    return file_sha256(path)


def _validate_hash_sidecar(report_dir: Path, filename: str, errors: list[str]) -> None:
    path = report_dir / filename
    hash_path = _hash_path(report_dir, filename)
    if not hash_path.exists():
        errors.append(f"{filename}: missing hash file {hash_path.relative_to(report_dir)}")
        return
    actual = _actual_digest(path)
    recorded = hash_path.read_text(errors="replace").split(None, 1)[0]
    if recorded != actual:
        errors.append(f"{filename}: hash file digest does not match artifact content")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--strict", action="store_true", help="Fail if an expected artifact is absent")
    args = parser.parse_args()

    report_dir = args.report_dir
    errors: list[str] = []
    validated: list[str] = []
    manifest_entries: dict[str, dict] = {}
    manifest_path = report_dir / "evidence-manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            manifest_entries = {
                item.get("file", ""): item
                for item in manifest.get("evidence_files", [])
                if item.get("file")
            }
        except Exception as exc:
            errors.append(f"evidence-manifest.json is not readable JSON: {exc}")
    elif args.strict:
        errors.append("missing expected artifact: evidence-manifest.json")

    for filename, item in sorted(manifest_entries.items()):
        path = report_dir / filename
        if not path.exists():
            errors.append(f"{filename}: listed in evidence-manifest.json but file is missing")
            continue
        if path.suffix == ".json":
            try:
                json.loads(path.read_text(errors="replace"))
            except Exception as exc:
                errors.append(f"{filename}: listed JSON artifact is not readable JSON: {exc}")
        actual = _actual_digest(path)
        expected = str(item.get("sha256", ""))
        if expected and expected != actual:
            errors.append(f"{filename}: evidence-manifest.json sha256 does not match artifact content")
        _validate_hash_sidecar(report_dir, filename, errors)

    artifact_specs = [(kind, filename, True) for kind, filename in REPORT_ARTIFACTS.items()]
    artifact_specs.extend((kind, filename, False) for kind, filename in OPTIONAL_REPORT_ARTIFACTS.items())

    for kind, filename, required in artifact_specs:
        path = report_dir / filename
        if not path.exists():
            if args.strict and required:
                errors.append(f"missing expected artifact: {filename}")
            continue
        try:
            load_target_artifact(path, kind, strict=args.strict)
            validated.append(filename)
        except TargetArtifactError as exc:
            errors.append(f"{filename}: {exc}")
        if manifest_entries and filename not in manifest_entries and filename != "graph-manifest.json":
            errors.append(f"{filename}: not listed in evidence-manifest.json evidence_files")
        elif manifest_entries and filename in manifest_entries:
            expected = str(manifest_entries[filename].get("sha256", ""))
            actual = _actual_digest(path)
            if expected and expected != actual:
                errors.append(f"{filename}: evidence-manifest.json sha256 does not match artifact content")
        _validate_hash_sidecar(report_dir, filename, errors)

    for claim_path in sorted((report_dir / "claims").glob("*.json")):
        rel = str(claim_path.relative_to(report_dir))
        claim_errors = verify_claim(claim_path, report_dir)
        if claim_errors:
            errors.extend(f"{rel}: {error}" for error in claim_errors)
        else:
            validated.append(rel)
        _validate_hash_sidecar(report_dir, rel, errors)

    for bundle_path in sorted((report_dir / "proof-bundles").glob("*.json")):
        rel = str(bundle_path.relative_to(report_dir))
        bundle_errors = verify_proof_bundle(bundle_path, report_dir)
        if bundle_errors:
            errors.extend(f"{rel}: {error}" for error in bundle_errors)
        else:
            validated.append(rel)
        _validate_hash_sidecar(report_dir, rel, errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK report artifacts: {', '.join(validated) if validated else 'none present'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
