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


def _dedupe_dicts(items: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = tuple(str(item.get(field) or "") for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _candidate_compliance_mappings(
    fr_id: str,
    tbt_ids: list[str],
    mapping_packs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidate_tbt_ids = set(tbt_ids)
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for pack in mapping_packs:
        compliance = pack.get("compliance") or {}
        default_ruleset = str(compliance.get("ruleset") or "")
        default_version = str(compliance.get("version") or "")
        for mapping in pack.get("mappings") or []:
            refs = mapping.get("blueprint_refs") or {}
            fr_refs = set(refs.get("fr_refs") or [])
            tbt_refs = set(refs.get("tbt_refs") or [])
            if fr_id not in fr_refs and candidate_tbt_ids.isdisjoint(tbt_refs):
                continue

            relationship = str(mapping.get("relationship") or "related")
            strength = str(mapping.get("traceability_strength") or "advisory")
            key = (default_ruleset, default_version, relationship, strength)
            group = grouped.setdefault(key, {
                "ruleset": default_ruleset,
                "version": default_version,
                "relationship": relationship,
                "traceability_strength": strength,
                "mapping_ids": [],
                "rows": [],
                "domains": [],
            })
            if mapping.get("id"):
                group["mapping_ids"].append(str(mapping["id"]))
            targets = mapping.get("targets") or {}
            group["rows"].extend(targets.get("compliance_rows") or [])
            group["domains"].extend(targets.get("compliance_domains") or [])

    summaries: list[dict[str, Any]] = []
    for group in grouped.values():
        group["mapping_ids"] = sorted(set(group["mapping_ids"]))
        group["rows"] = _dedupe_dicts(group["rows"], ("ruleset", "row"))
        group["domains"] = _dedupe_dicts(group["domains"], ("ruleset", "domain"))
        summaries.append(group)
    return sorted(summaries, key=lambda item: (item["ruleset"], item["version"], item.get("relationship") or ""))


def _rulesets_from_mappings(mappings: list[dict[str, Any]]) -> set[str]:
    return {str(mapping.get("ruleset")) for mapping in mappings if mapping.get("ruleset")}


def build_blueprint_candidates(
    blueprint_path: Path,
    *,
    config_selection: dict[str, Any] | None = None,
    include_all: bool = False,
    mapping_packs: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog = load_fr_catalog(blueprint_path).raw
    selected = selected_rulesets(config_selection)
    mapping_packs = mapping_packs or []
    profile = catalog.get("blueprint_profile") or {}
    source_ref = {
        "id": str((catalog.get("project") or blueprint_path.parent.parent.name)),
        "version": str(profile.get("version") or ((catalog.get("scope") or {}).get("ASVS") or {}).get("version") or blueprint_path.parent.name),
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
        tbt_ids = [str(tbt["id"]) for tbt in related_tbts if tbt.get("id")]
        compliance_mappings = _candidate_compliance_mappings(str(fr["id"]), tbt_ids, mapping_packs)
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
        rulesets.update(_rulesets_from_mappings(compliance_mappings))
        if not include_all and selected and rulesets.isdisjoint(selected):
            continue
        candidate = {
            "id": f"CANDIDATE-{fr['id']}",
            "blueprint_fr": fr["id"],
            "blueprint_tbts": tbt_ids,
            "decision": "pending_review",
            "rationale": "Blueprint FR/TBT chain matches the selected compliance rulesets and should be reviewed for project applicability.",
            "confidence": "medium",
            "assumptions": [
                "Blueprint selection is not evidence.",
                "Accepted candidates must still be emitted as reviewed config-update proposals.",
            ],
        }
        if compliance_mappings:
            candidate["compliance_mappings"] = compliance_mappings
        candidates.append(candidate)
    return source_ref, candidates
