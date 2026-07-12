#!/usr/bin/env python3
"""Update or validate the report-local Project FR board state artifact."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from artifact_hashing import file_sha256, write_hash_sidecar
from load_target_artifacts import TargetArtifactError, load_target_artifact


VALID_LANES = {"map", "recommended", "specify", "review", "import", "blocked"}
VALID_DECISIONS = {
    "",
    "accept_recommendation",
    "remap_as_orphan",
    "leave_unmapped",
    "mark_not_assurance_relevant",
    "needs_new_tbt_fr",
    "approve_for_implementation",
    "approve_to_run",
    "send_back_to_review",
    "blocked",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(errors="replace"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {path}: {exc}") from exc


def evidence_manifest(report_dir: Path) -> dict[str, Any]:
    path = report_dir / "evidence-manifest.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(errors="replace"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def normalise_cards(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("cards"), list):
        source_cards = raw["cards"]
    elif isinstance(raw, dict):
        source_cards = []
        for card_id, value in raw.items():
            if isinstance(value, str):
                source_cards.append({"id": card_id, "lane": value})
            elif isinstance(value, dict):
                source_cards.append({"id": card_id, **value})
    elif isinstance(raw, list):
        source_cards = raw
    else:
        raise SystemExit("board state must be an object with cards, an id-to-card object, or a card array")

    cards: list[dict[str, Any]] = []
    for item in source_cards:
        if not isinstance(item, dict):
            raise SystemExit("every board-state card must be an object")
        card_id = str(item.get("id") or "").strip()
        if not card_id:
            raise SystemExit("every board-state card requires id")
        lane = str(item.get("lane") or "").strip()
        if lane not in VALID_LANES:
            raise SystemExit(f"card {card_id}: invalid lane {lane!r}")
        decision = str(item.get("decision") or "").strip()
        if decision not in VALID_DECISIONS:
            raise SystemExit(f"card {card_id}: invalid decision {decision!r}")
        cards.append({
            "id": card_id,
            "lane": lane,
            "source": str(item.get("source") or ""),
            "title": str(item.get("title") or ""),
            "native_path": str(item.get("native_path") or ""),
            "pack_path": str(item.get("pack_path") or ""),
            "tbt": str(item.get("tbt") or ""),
            "frs": [str(fr) for fr in item.get("frs") or [] if fr],
            "target": str(item.get("target") or ""),
            "recommendation": str(item.get("recommendation") or ""),
            "decision": decision,
            "reviewer_note": str(item.get("reviewer_note") or ""),
            "manual_test_path": str(item.get("manual_test_path") or ""),
            "agentic_rationale": str(item.get("agentic_rationale") or ""),
            "discovery_rationale": str(item.get("discovery_rationale") or ""),
            "confidence": str(item.get("confidence") or ""),
            "type": str(item.get("type") or ""),
            "status": str(item.get("status") or ""),
            "assessment": str(item.get("assessment") or ""),
            "safety": str(item.get("safety") or ""),
            "updated_at": str(item.get("updated_at") or ""),
        })
    return cards


def build_state(report_dir: Path, raw: Any) -> dict[str, Any]:
    manifest = evidence_manifest(report_dir)
    cards = normalise_cards(raw)
    generated_at = str(
        raw.get("generated_at")
        if isinstance(raw, dict) and raw.get("generated_at")
        else manifest.get("generated_at") or "1970-01-01T00:00:00Z"
    )
    for card in cards:
        if not card.get("updated_at"):
            card["updated_at"] = generated_at
    return {
        "schema_version": 1,
        "mode": "project_fr_board_state",
        "project": str(
            raw.get("project")
            if isinstance(raw, dict) and raw.get("project")
            else manifest.get("repository") or manifest.get("repo_name") or "target-project"
        ),
        "run_id": str(
            raw.get("run_id")
            if isinstance(raw, dict) and raw.get("run_id")
            else manifest.get("run_id") or report_dir.name
        ),
        "generated_at": generated_at,
        "cards": cards,
    }


def record_report_artifact(report_dir: Path, artifact: Path) -> None:
    manifest_path = report_dir / "evidence-manifest.json"
    if not manifest_path.exists():
        write_hash_sidecar(report_dir, artifact)
        return
    manifest = json.loads(manifest_path.read_text(errors="replace"))
    rel = str(artifact.relative_to(report_dir))
    digest = file_sha256(artifact)
    files = [item for item in manifest.get("evidence_files", []) if item.get("file") != rel]
    files.append({"file": rel, "bytes": artifact.stat().st_size, "sha256": digest})
    manifest["evidence_files"] = sorted(files, key=lambda item: item.get("file", ""))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    write_hash_sidecar(report_dir, artifact)


def refresh_dashboard(report_dir: Path) -> None:
    script_dir = Path(__file__).resolve().parent
    cmd = [sys.executable, str(script_dir / "generate_dashboard.py"), "--report-dir", str(report_dir)]
    optional_inputs = [
        ("--fr-catalog", report_dir / "fr-catalog.snapshot.json"),
        ("--assurance-framework", report_dir / "assurance-framework.snapshot.json"),
        ("--assurance-instance", report_dir / "assurance-instance.snapshot.json"),
        ("--compliance-mapping-pack", report_dir / "compliance-mapping-pack.snapshot.json"),
        ("--scanner-compliance-mapping-pack", report_dir / "scanner-compliance-mapping-packs"),
    ]
    for flag, path in optional_inputs:
        if path.exists():
            cmd.extend([flag, str(path)])
    subprocess.run(cmd, check=True)


def validate_state(path: Path, *, strict: bool) -> None:
    load_target_artifact(path, "project_fr_board_state", strict=strict)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", type=Path)
    parser.add_argument("--state-json", help="JSON file containing board-state cards to write, or '-' for stdin")
    parser.add_argument("--validate-only", action="store_true", help="Validate the existing project-fr-board-state.json")
    parser.add_argument("--strict", action="store_true", help="Treat semantic warnings as validation errors")
    parser.add_argument("--refresh-dashboard", action="store_true", help="Regenerate dashboard.html after writing state")
    args = parser.parse_args()

    report_dir = args.report_dir.resolve()
    if not report_dir.is_dir():
        raise SystemExit(f"report directory not found: {report_dir}")
    state_path = report_dir / "project-fr-board-state.json"
    try:
        if args.validate_only:
            validate_state(state_path, strict=args.strict)
            print(f"OK project FR board state: {state_path}")
            return 0
        if not args.state_json:
            raise SystemExit("provide --state-json or --validate-only")
        raw = json.load(sys.stdin) if args.state_json == "-" else load_json(Path(args.state_json))
        state = build_state(report_dir, raw)
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        validate_state(state_path, strict=args.strict)
        record_report_artifact(report_dir, state_path)
        if args.refresh_dashboard:
            refresh_dashboard(report_dir)
        print(f"project FR board state updated: {state_path}")
        print(f"cards: {len(state['cards'])}")
        print(f"sha256: {file_sha256(state_path)}")
        return 0
    except TargetArtifactError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
