#!/usr/bin/env python3
"""Propose reusable blueprint FR/TBT chains for a project planning session."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from artifact_hashing import file_sha256
from load_target_artifacts import TargetArtifactError, load_target_artifact
from planning_studio.atomic.blueprint_recommender import (
    build_blueprint_candidates,
    build_blueprint_selection_proposal,
)
from planning_studio.storage import with_content_hash


def _load_config_selection(path: Path | None) -> dict | None:
    if not path:
        return None
    return load_target_artifact(path, "project_config_selection", strict=True).raw


def _load_mapping_pack_refs(paths: list[Path]) -> tuple[list[dict], list[dict]]:
    packs: list[dict] = []
    refs: list[dict] = []
    for path in paths:
        artifact = load_target_artifact(path, "blueprint_compliance_mapping_pack", strict=True)
        pack = artifact.raw
        packs.append(pack)
        pack_meta = pack.get("pack") or {}
        refs.append({
            "id": str(pack_meta.get("pack_id") or path.stem),
            "version": str(pack_meta.get("pack_version") or "unknown"),
            "path": str(path),
            "sha256": file_sha256(path, prefixed=True),
            "blueprint": {
                "catalog": str((pack.get("blueprint") or {}).get("catalog") or "unknown"),
                "version": str((pack.get("blueprint") or {}).get("version") or "unknown"),
            },
            "compliance": {
                "ruleset": str((pack.get("compliance") or {}).get("ruleset") or "unknown"),
                "version": str((pack.get("compliance") or {}).get("version") or "unknown"),
            },
        })
    return packs, refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Project identifier for the proposal")
    parser.add_argument("--blueprint", action="append", type=Path, required=True, help="Blueprint FR catalog JSON")
    parser.add_argument("--config-selection", type=Path, help="Planning Studio project config selection JSON")
    parser.add_argument(
        "--blueprint-compliance-mapping-pack",
        action="append",
        type=Path,
        default=[],
        help="Reviewed blueprint-to-compliance mapping pack JSON to attach to proposed candidates",
    )
    parser.add_argument("--include-all", action="store_true", help="Propose all blueprint FRs without filtering by config selection")
    parser.add_argument("--output", type=Path, required=True, help="Output blueprint selection proposal JSON")
    args = parser.parse_args()

    try:
        config_selection = _load_config_selection(args.config_selection)
        mapping_packs, source_mapping_packs = _load_mapping_pack_refs(args.blueprint_compliance_mapping_pack)
        source_blueprints = []
        candidates = []
        for blueprint in args.blueprint:
            source_ref, blueprint_candidates = build_blueprint_candidates(
                blueprint,
                config_selection=config_selection,
                include_all=args.include_all,
                mapping_packs=mapping_packs,
            )
            source_blueprints.append(source_ref)
            candidates.extend(blueprint_candidates)
        proposal = with_content_hash(build_blueprint_selection_proposal(
            args.project,
            source_blueprints,
            candidates,
            source_mapping_packs=source_mapping_packs,
        ))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(proposal, indent=2) + "\n")
        load_target_artifact(args.output, "blueprint_selection_proposal", strict=True)
    except TargetArtifactError as exc:
        print(f"ERROR: {exc}")
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"OK blueprint proposal: {len(candidates)} candidate(s)")
    print(f"  output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
