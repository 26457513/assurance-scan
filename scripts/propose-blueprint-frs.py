#!/usr/bin/env python3
"""Propose reusable blueprint FR/TBT chains for a project planning session."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Project identifier for the proposal")
    parser.add_argument("--blueprint", action="append", type=Path, required=True, help="Blueprint FR catalog JSON")
    parser.add_argument("--config-selection", type=Path, help="Planning Studio project config selection JSON")
    parser.add_argument("--include-all", action="store_true", help="Propose all blueprint FRs without filtering by config selection")
    parser.add_argument("--output", type=Path, required=True, help="Output blueprint selection proposal JSON")
    args = parser.parse_args()

    try:
        config_selection = _load_config_selection(args.config_selection)
        source_blueprints = []
        candidates = []
        for blueprint in args.blueprint:
            source_ref, blueprint_candidates = build_blueprint_candidates(
                blueprint,
                config_selection=config_selection,
                include_all=args.include_all,
            )
            source_blueprints.append(source_ref)
            candidates.extend(blueprint_candidates)
        proposal = with_content_hash(build_blueprint_selection_proposal(
            args.project,
            source_blueprints,
            candidates,
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
