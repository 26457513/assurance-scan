from __future__ import annotations

from pathlib import Path
from typing import Any

from artifact_hashing import file_sha256
from load_fr_catalog import load_fr_catalog


def build_blueprint_selection_proposal(
    project: str,
    source_blueprints: list[dict],
    candidates: list[dict],
    **extra: object,
) -> dict:
    return {
        "schema_version": 1,
        "id": extra.pop("id", f"BLUEPRINT-PROPOSAL-{project}"),
        "status": "review_required",
        "project": project,
        "source_blueprints": source_blueprints,
        "candidates": candidates,
        **extra,
    }


def selected_rulesets(config_selection: dict[str, Any] | None) -> set[str]:
    if not config_selection:
        return set()
    rulesets: set[str] = set()
    for selection in config_selection.get("selections") or []:
        package_type = str(selection.get("package_type") or "").lower()
        if package_type in {"ruleset", "compliance_ruleset", "compliance_regime", "compliance"} and selection.get("id"):
            rulesets.add(str(selection["id"]))
    return rulesets


def build_blueprint_candidates(
    blueprint_path: Path,
    *,
    config_selection: dict[str, Any] | None = None,
    include_all: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog = load_fr_catalog(blueprint_path).raw
    selected = selected_rulesets(config_selection)
    source_ref = {
        "id": str((catalog.get("project") or blueprint_path.parent.parent.name)),
        "version": str(((catalog.get("scope") or {}).get("ASVS") or {}).get("version") or blueprint_path.parent.name),
        "path": str(blueprint_path),
        "sha256": file_sha256(blueprint_path, prefixed=True),
    }
    tbts_by_fr: dict[str, list[dict[str, Any]]] = {}
    for tbt in catalog.get("tbts") or []:
        for fr_id in tbt.get("proves") or []:
            tbts_by_fr.setdefault(fr_id, []).append(tbt)

    candidates: list[dict[str, Any]] = []
    for fr in catalog.get("frs") or []:
        related_tbts = tbts_by_fr.get(fr.get("id"), [])
        rulesets = {
            row.get("ruleset")
            for row in (fr.get("satisfies") or [])
            if row.get("ruleset")
        }
        for tbt in related_tbts:
            rulesets.update(
                row.get("ruleset")
                for row in (tbt.get("compliance") or [])
                if row.get("ruleset")
            )
        if not include_all and selected and rulesets.isdisjoint(selected):
            continue
        candidates.append({
            "id": f"CANDIDATE-{fr['id']}",
            "blueprint_fr": fr["id"],
            "blueprint_tbts": [tbt["id"] for tbt in related_tbts],
            "decision": "pending_review",
            "rationale": "Blueprint FR/TBT chain matches the selected compliance rulesets and should be reviewed for project applicability.",
            "confidence": "medium",
            "assumptions": [
                "Blueprint selection is not evidence.",
                "Accepted candidates must still be emitted as reviewed config-update proposals.",
            ],
        })
    return source_ref, candidates
