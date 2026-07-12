#!/usr/bin/env python3
"""Convert reviewed blueprint decisions into a review-gated config update proposal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from load_target_artifacts import TargetArtifactError, load_target_artifact
from planning_studio.atomic.blueprint_config_update import build_config_update_from_blueprint_decisions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Project identifier")
    parser.add_argument("--run-id", required=True, help="Planning or scan run identifier")
    parser.add_argument("--proposal", type=Path, required=True, help="Blueprint selection proposal JSON")
    parser.add_argument("--decisions", type=Path, required=True, help="Blueprint decision log JSON")
    parser.add_argument("--blueprint", action="append", type=Path, required=True, help="Blueprint FR catalog JSON")
    parser.add_argument("--output", type=Path, required=True, help="Output config update proposal JSON")
    args = parser.parse_args()

    try:
        proposal = load_target_artifact(args.proposal, "blueprint_selection_proposal", strict=True).raw
        decisions = load_target_artifact(args.decisions, "blueprint_decision_log", strict=True).raw
        config_update = build_config_update_from_blueprint_decisions(
            project=args.project,
            run_id=args.run_id,
            proposal=proposal,
            decision_log=decisions,
            blueprint_paths=args.blueprint,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(config_update, indent=2) + "\n")
        load_target_artifact(args.output, "config_update_proposal", strict=True)
    except TargetArtifactError as exc:
        print(f"ERROR: {exc}")
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"OK config update proposal: {len(config_update.get('fr_catalog_updates') or [])} FR/TBT update(s)")
    print(f"  output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
