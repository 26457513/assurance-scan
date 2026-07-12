from __future__ import annotations

from artifact_hashing import canonical_json_sha256


def recompute_contract_hash(payload: dict) -> dict:
    updated = dict(payload)
    updated.pop("contract_hash", None)
    updated.pop("content_hash", None)
    contract_hash = canonical_json_sha256(updated)
    updated["contract_hash"] = contract_hash
    return updated


def build_resolved_project_planning_contract(
    project: str,
    source_artifacts: list[dict],
    sections: dict,
    **extra: object,
) -> dict:
    section_hashes = {
        key: canonical_json_sha256(value)
        for key, value in sorted(sections.items())
    }
    payload = {
        "schema_version": 1,
        "id": extra.pop("id", f"PLANNING-CONTRACT-{project}"),
        "status": extra.pop("status", "draft"),
        "project": project,
        "source_artifacts": source_artifacts,
        "sections": sections,
        "open_assumptions": extra.pop("open_assumptions", []),
        "section_hashes": section_hashes,
        **extra,
    }
    return recompute_contract_hash(payload)
