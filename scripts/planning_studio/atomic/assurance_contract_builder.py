from __future__ import annotations


def build_project_assurance_contract(
    project: str,
    planning_contract: dict,
    artifacts: list[dict],
    **extra: object,
) -> dict:
    return {
        "schema_version": 1,
        "id": extra.pop("id", f"ASSURANCE-CONTRACT-{project}"),
        "project": project,
        "derived_from_contract": planning_contract["id"],
        "derived_from_contract_hash": planning_contract.get("contract_hash"),
        "artifacts": artifacts,
        "notes": extra.pop("notes", ["Derived export only; not a second source of truth."]),
        **extra,
    }

