#!/usr/bin/env python3
"""Render a human review brief for a config update proposal.

This is intentionally read-only. It summarizes proposed edits, highlights weak
confidence and review questions, and leaves application to a separate reviewed
step.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from load_target_artifacts import TargetArtifactError, load_target_artifact


UPDATE_SECTIONS = [
    ("fr_catalog_updates", "FR Catalog Updates"),
    ("compliance_mapping_pack_updates", "Compliance Mapping Updates"),
    ("assurance_framework_or_instance_updates", "Framework / Instance Updates"),
    ("manual_evidence_updates", "Manual Evidence Updates"),
    ("native_test_mapping_updates", "Native Test Mapping Updates"),
]
APPLYABLE_SECTIONS = {
    "fr_catalog_updates",
    "compliance_mapping_pack_updates",
    "native_test_mapping_updates",
}


def _label_update(update: dict[str, Any]) -> str:
    parts = [str(update.get("operation", "update"))]
    if update.get("fr_id"):
        parts.append(str(update["fr_id"]))
    if update.get("tbt_id"):
        parts.append(str(update["tbt_id"]))
    if update.get("ruleset") and update.get("row_id"):
        parts.append(f"{update['ruleset']} {update['row_id']}")
    if update.get("scanner"):
        parts.append(str(update["scanner"]))
    native_test = update.get("native_test") or {}
    if native_test.get("native_path"):
        parts.append(str(native_test["native_path"]))
    target = update.get("target") or {}
    if target.get("kind") and target.get("id"):
        parts.append(f"{target['kind']} {target['id']}")
    return " · ".join(parts)


def _source_count(update: dict[str, Any]) -> int:
    return len(update.get("source_basis") or [])


def _confidence(update: dict[str, Any]) -> str:
    return str(update.get("confidence") or "unknown")


def _risk(update: dict[str, Any]) -> str:
    confidence = _confidence(update)
    review_status = update.get("review_status")
    source_count = _source_count(update)
    if review_status == "needs_review" or confidence == "low":
        return "needs assessor review"
    if source_count == 0:
        return "missing provenance"
    if confidence == "medium":
        return "review recommended"
    return "candidate"


def _apply_mode(section: str) -> str:
    return "applyable" if section in APPLYABLE_SECTIONS else "review-only"


def _is_applyable_update(section: str, update: dict[str, Any]) -> bool:
    if section in APPLYABLE_SECTIONS:
        return True
    if section == "assurance_framework_or_instance_updates":
        operation = update.get("operation")
        target = update.get("target") or {}
        if operation in {"add_instance_mapping", "update_instance_mapping"}:
            return target.get("kind") in {"criterion", "gate", "role"}
        if operation in {"add_decision", "update_decision"}:
            return target.get("kind") in {"gate", "decision"}
        if operation in {"add_waiver", "update_waiver"}:
            return target.get("kind") in {"fr", "tbt", "ruleset_row", "gate", "criterion", "waiver"}
        if operation in {"add_compensating_control", "update_compensating_control"}:
            return target.get("kind") in {"fr", "tbt", "ruleset_row", "gate", "criterion", "compensating_control"}
        return False
    if section == "manual_evidence_updates":
        target = update.get("target") or {}
        proposed = update.get("proposed_fields") or {}
        target_kind = target.get("kind")
        if target_kind in {"fr", "tbt", "criterion"}:
            return True
        if target_kind == "gate":
            return bool(proposed.get("criterion") or proposed.get("criterion_id"))
        if target_kind == "role":
            return bool((proposed.get("gate") or proposed.get("gate_id")) and (proposed.get("role") or proposed.get("role_id") or target.get("id")))
    return False


def _update_apply_mode(section: str, update: dict[str, Any]) -> str:
    return "applyable" if _is_applyable_update(section, update) else "review-only"


def _selector(section: str, index: int) -> str:
    return f"{section}:{index}"


def _update_rows(section: str, updates: list[dict[str, Any]]) -> list[str]:
    rows = ["| Selector | Mode | Proposal | Status | Confidence | Sources | Risk |", "|---|---|---|---|---|---:|---|"]
    for index, update in enumerate(updates, start=1):
        rows.append(
            "| "
            + " | ".join(
                [
                    f"`{_selector(section, index)}`",
                    _update_apply_mode(section, update),
                    _escape(_label_update(update)),
                    _escape(str(update.get("review_status", ""))),
                    _escape(_confidence(update)),
                    str(_source_count(update)),
                    _escape(_risk(update)),
                ]
            )
            + " |"
        )
    return rows


def _escape(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ")


def _brief(proposal: dict[str, Any]) -> str:
    update_count = sum(len(proposal.get(section) or []) for section, _ in UPDATE_SECTIONS)
    low_confidence = [
        _label_update(update)
        for section, _ in UPDATE_SECTIONS
        for update in proposal.get(section) or []
        if _confidence(update) == "low"
    ]
    needs_review = [
        _label_update(update)
        for section, _ in UPDATE_SECTIONS
        for update in proposal.get(section) or []
        if update.get("review_status") == "needs_review"
    ]

    md: list[str] = []
    md.append("# Config Update Proposal Review")
    md.append("")
    md.append(f"- Project: `{proposal.get('project')}`")
    md.append(f"- Run ID: `{proposal.get('run_id')}`")
    md.append(f"- Proposed updates: `{update_count}`")
    md.append(f"- Uncertain mappings: `{len(proposal.get('uncertain_mappings') or [])}`")
    md.append(f"- Review questions: `{len(proposal.get('review_required') or [])}`")
    md.append("")
    md.append("## Recommendation")
    md.append("")
    if low_confidence or needs_review or proposal.get("uncertain_mappings") or proposal.get("review_required"):
        md.append("Review before applying. The proposal contains low-confidence items, explicit review questions, or uncertain mappings.")
    else:
        md.append("Candidate for controlled application after human approval. No low-confidence or uncertain items were declared.")
    md.append("")
    md.append("## Source Inputs")
    md.append("")
    for item in proposal.get("source_inputs") or []:
        md.append(f"- `{item.get('path')}`: {item.get('used_for', '')}")
    md.append("")

    for section, title in UPDATE_SECTIONS:
        updates = proposal.get(section) or []
        if not updates:
            continue
        md.append(f"## {title}")
        md.append("")
        md.extend(_update_rows(section, updates))
        md.append("")
        for index, update in enumerate(updates, start=1):
            selector = _selector(section, index)
            md.append(f"### {_label_update(update)}")
            md.append("")
            md.append(f"- Selector: `{selector}`")
            md.append(f"- Apply mode: `{_update_apply_mode(section, update)}`")
            md.append(f"- Rationale: {update.get('rationale', '')}")
            md.append(f"- Confidence: `{_confidence(update)}`")
            md.append(f"- Review status: `{update.get('review_status', '')}`")
            if _is_applyable_update(section, update):
                md.append(f"- Apply after approval: `asvs-scanner apply-config-update proposal.json --select {selector} --reviewed-by <name> ... --*-out <reviewed-file>`")
            else:
                md.append("- Apply after approval: manual/review-only in this version.")
            if update.get("limitations"):
                md.append("- Limitations:")
                for limitation in update.get("limitations") or []:
                    md.append(f"  - {limitation}")
            if update.get("source_basis"):
                md.append("- Source basis:")
                for source in update.get("source_basis") or []:
                    md.append(f"  - `{source.get('type')}` `{source.get('ref')}`")
            md.append("")

    if proposal.get("uncertain_mappings"):
        md.append("## Uncertain Mappings")
        md.append("")
        for item in proposal.get("uncertain_mappings") or []:
            refs = ", ".join(str(ref) for ref in item.get("refs") or [])
            md.append(f"- `{item.get('kind')}` {refs}: {item.get('question')} ({item.get('why')})")
        md.append("")

    if proposal.get("review_required"):
        md.append("## Review Required")
        md.append("")
        for item in proposal.get("review_required") or []:
            md.append(f"- `{item.get('item')}`: {item.get('question')} ({item.get('why')})")
        md.append("")

    md.append("## Next Step")
    md.append("")
    md.append("Validate this proposal with `scripts/validate-config-update-proposal.py`, then approve or reject each proposed update before applying any catalog changes.")
    md.append("")
    return "\n".join(md)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--output", type=Path, help="Write markdown review brief to this path")
    args = parser.parse_args()

    try:
        proposal = load_target_artifact(args.proposal, "config_update_proposal").raw
    except TargetArtifactError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    text = _brief(proposal)
    if args.output:
        args.output.write_text(text)
        print(f"OK wrote proposal review: {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
