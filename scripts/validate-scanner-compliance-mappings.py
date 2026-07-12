#!/usr/bin/env python3
"""Validate scanner-to-compliance mapping packs.

Each pack is intentionally file-specific: one scanner, one compliance regime,
one compliance version. This keeps future ASVS/NIST/CIS mappings separate and
prevents scanner-rule version drift from being hidden inside a large mixed file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from load_target_artifacts import TargetArtifactError, load_target_artifact


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def ruleset_file_for(ruleset_root: Path, ruleset: str, version: str) -> Path:
    return ruleset_root / ruleset.lower() / f"{version}.json"


def ruleset_rows_for(pack: dict[str, Any], ruleset_root: Path) -> set[tuple[str, str]]:
    compliance = pack.get("compliance") or {}
    ruleset = compliance.get("ruleset")
    version = compliance.get("version")
    if not ruleset or not version:
        return set()
    req_path = ruleset_file_for(ruleset_root, str(ruleset), str(version))
    if not req_path.exists():
        return set()
    try:
        artifact = load_target_artifact(req_path, "ruleset", strict=True)
    except TargetArtifactError:
        return set()
    rows = artifact.raw.get("rows") or []
    return {(ruleset, row.get("id")) for row in rows if row.get("id")}


def validate_pack(path: Path, ruleset_root: Path) -> list[str]:
    errors: list[str] = []
    try:
        artifact = load_target_artifact(path, "scanner_compliance_mapping_pack", strict=True)
    except TargetArtifactError as exc:
        return [f"{path}: {error}" for error in exc.errors]

    pack = artifact.raw
    rows = ruleset_rows_for(pack, ruleset_root)
    compliance = pack.get("compliance") or {}
    if not rows:
        errors.append(
            f"{path}: cannot load ruleset rows for {compliance.get('ruleset')} {compliance.get('version')}"
        )
        return errors

    seen: set[str] = set()
    for mapping in pack.get("mappings") or []:
        mapping_id = mapping.get("id")
        if mapping_id in seen:
            errors.append(f"{path}: duplicate mapping id {mapping_id}")
        seen.add(mapping_id)
        targets = mapping.get("targets") or {}
        if mapping.get("mapping_level") == "compliance_row" and not targets.get("compliance_rows"):
            errors.append(f"{path}: mapping {mapping_id} is compliance_row but has no compliance row targets")
        if mapping.get("mapping_level") == "compliance_domain" and not targets.get("compliance_domains"):
            errors.append(f"{path}: mapping {mapping_id} is compliance_domain but has no compliance domain targets")
        if mapping.get("mapping_level") == "general_finding":
            if targets.get("compliance_rows") or targets.get("compliance_domains"):
                errors.append(f"{path}: mapping {mapping_id} is general_finding but declares compliance targets")
        for row in targets.get("compliance_rows") or []:
            key = (row.get("ruleset"), row.get("row"))
            if key not in rows:
                errors.append(f"{path}: mapping {mapping_id} references unknown compliance row {key}")
        if mapping.get("review_status") == "accepted" and not mapping.get("limitations"):
            errors.append(f"{path}: accepted mapping {mapping_id} must document limitations")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path("data/scanner-mappings")],
        help="Mapping pack files or directories to validate.",
    )
    parser.add_argument(
        "--ruleset-root",
        type=Path,
        default=Path("data/rulesets"),
        help="Directory containing canonical versioned ruleset snapshots.",
    )
    args = parser.parse_args()

    files: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.json")))
        else:
            files.append(path)

    errors: list[str] = []
    for path in files:
        errors.extend(validate_pack(path, args.ruleset_root))

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK scanner compliance mapping packs: {len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
