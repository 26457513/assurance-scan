#!/usr/bin/env python3
"""Apply reviewed blueprint scope decisions into a reviewed project FR catalog.

This is the product-level wrapper for the blueprint consolidation workflow. It
keeps the lower-level artifacts for audit, but lets users run one command after
reviewing the proposed FR scope.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from load_target_artifacts import TargetArtifactError, load_target_artifact
from planning_studio.atomic.blueprint_config_update import build_config_update_from_blueprint_decisions


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLUEPRINT = REPO_ROOT / "data" / "blueprints" / "security-core" / "asvs-5.0.0" / "fr-catalog.blueprint.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _run(args: list[str]) -> None:
    completed = subprocess.run(args, cwd=REPO_ROOT, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(args)}")


def _accept_all_decisions(*, proposal: dict[str, Any], project: str, reviewed_by: str, reason: str) -> dict[str, Any]:
    reviewed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "id": f"BLUEPRINT-DECISIONS-{project}",
        "project": project,
        "proposal": str(proposal.get("id") or "blueprint-proposal"),
        "decisions": [
            {
                "candidate": candidate["id"],
                "decision": "accepted_as_is",
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
                "reason": reason,
            }
            for candidate in proposal.get("candidates") or []
            if candidate.get("id")
        ],
    }


def _resolve_user_path(path: Path, *, cwd: Path) -> Path:
    return path if path.is_absolute() else cwd / path


def _bootstrap_catalog(*, project: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": project,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "scope": {},
        "na_rows": [],
        "frs": [],
        "tbts": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Project identifier. Defaults to blueprint-proposal.json project.")
    parser.add_argument("--run-id", required=True, help="Planning or scan run identifier")
    parser.add_argument("--proposal", type=Path, default=Path("blueprint-proposal.json"), help="Blueprint selection proposal JSON")
    parser.add_argument("--decisions", type=Path, default=Path("blueprint-decisions.json"), help="Reviewed blueprint decision log JSON")
    parser.add_argument("--blueprint", action="append", type=Path, default=[], help="Blueprint FR catalog JSON. Defaults to security-core ASVS blueprint.")
    parser.add_argument("--proposal-out", type=Path, default=Path("proposal.json"), help="Config update proposal output")
    parser.add_argument("--review-out", type=Path, default=Path("proposal-review.md"), help="Human review brief output")
    parser.add_argument("--fr-catalog", type=Path, required=True, help="Existing project FR catalog input")
    parser.add_argument("--fr-catalog-out", type=Path, required=True, help="Reviewed project FR catalog output")
    parser.add_argument("--reviewed-by", required=True, help="Reviewer identity recorded on accepted outputs")
    parser.add_argument("--select", action="append", default=["fr_catalog_updates:*"], help="Config update selector(s) to apply")
    parser.add_argument("--accept-all-blueprints", action="store_true", help="Explicitly accept every candidate in blueprint-proposal.json as-is and write blueprint-decisions.json")
    parser.add_argument("--decision-reason", default="Accepted reviewed blueprint FR/TBT scope for this project.")
    parser.add_argument("--overwrite-decisions", action="store_true", help="Allow --accept-all-blueprints to overwrite an existing decisions file")
    args = parser.parse_args()
    invocation_cwd = Path.cwd()
    proposal_path = _resolve_user_path(args.proposal, cwd=invocation_cwd)
    decisions_path = _resolve_user_path(args.decisions, cwd=invocation_cwd)
    proposal_out_path = _resolve_user_path(args.proposal_out, cwd=invocation_cwd)
    review_out_path = _resolve_user_path(args.review_out, cwd=invocation_cwd)
    fr_catalog_path = _resolve_user_path(args.fr_catalog, cwd=invocation_cwd)
    fr_catalog_out_path = _resolve_user_path(args.fr_catalog_out, cwd=invocation_cwd)

    try:
        proposal_artifact = load_target_artifact(proposal_path, "blueprint_selection_proposal", strict=True).raw
        project = args.project or str(proposal_artifact.get("project") or "target-project")
        blueprint_paths = [
            path if path.is_absolute() else invocation_cwd / path
            for path in (args.blueprint or [DEFAULT_BLUEPRINT])
        ]
        for path in blueprint_paths:
            if not path.exists():
                raise FileNotFoundError(f"blueprint catalog not found: {path}")
        fresh_catalog = False
        if not fr_catalog_path.exists():
            fresh_catalog = True
            _write_json(fr_catalog_path, _bootstrap_catalog(project=project))
            print(f"OK created bootstrap FR catalog for fresh project: {fr_catalog_path}")

        if args.accept_all_blueprints:
            if decisions_path.exists() and not args.overwrite_decisions:
                raise FileExistsError(f"decisions file already exists: {decisions_path} (use --overwrite-decisions to replace it)")
            decision_log = _accept_all_decisions(
                proposal=proposal_artifact,
                project=project,
                reviewed_by=args.reviewed_by,
                reason=args.decision_reason,
            )
            _write_json(decisions_path, decision_log)
            print(f"OK blueprint decisions: accepted {len(decision_log['decisions'])} candidate(s)")
            print(f"  output: {decisions_path}")
        elif not decisions_path.exists():
            raise FileNotFoundError(
                f"reviewed decisions file not found: {args.decisions}. Review blueprint-proposal.json first, "
                "or rerun with --accept-all-blueprints for an explicit accept-all review."
            )

        decisions_artifact = load_target_artifact(decisions_path, "blueprint_decision_log", strict=True).raw
        config_update = build_config_update_from_blueprint_decisions(
            project=project,
            run_id=args.run_id,
            proposal=proposal_artifact,
            decision_log=decisions_artifact,
            blueprint_paths=blueprint_paths,
        )
        _write_json(proposal_out_path, config_update)
        load_target_artifact(proposal_out_path, "config_update_proposal", strict=True)
        print(f"OK config update proposal: {len(config_update.get('fr_catalog_updates') or [])} FR/TBT update(s)")
        print(f"  output: {proposal_out_path}")

        validate_args = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "validate-config-update-proposal.py"),
            str(proposal_out_path),
        ]
        if not fresh_catalog:
            validate_args.extend(["--fr-catalog", str(fr_catalog_path)])
        _run(validate_args)
        _run([
            sys.executable,
            str(REPO_ROOT / "scripts" / "review-config-update-proposal.py"),
            str(proposal_out_path),
            "--output",
            str(review_out_path),
        ])
        apply_args = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "apply-config-update-proposal.py"),
            str(proposal_out_path),
        ]
        for selector in args.select:
            apply_args.extend(["--select", selector])
        apply_args.extend([
            "--reviewed-by",
            args.reviewed_by,
            "--fr-catalog",
            str(fr_catalog_path),
            "--fr-catalog-out",
            str(fr_catalog_out_path),
        ])
        _run(apply_args)
    except (TargetArtifactError, FileNotFoundError, FileExistsError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("OK reviewed scope applied")
    print(f"  reviewed FR catalog: {fr_catalog_out_path}")
    print("Next: run assurance-scan scan with --fr-catalog pointing at the reviewed catalog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
