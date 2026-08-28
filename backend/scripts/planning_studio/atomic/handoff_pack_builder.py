from __future__ import annotations

from planning_studio.validators import assert_handoff_allowed


def build_code_studio_handoff(project: str, planning_contract: dict, context: dict, **extra: object) -> dict:
    assert_handoff_allowed(planning_contract)
    return {
        "schema_version": 1,
        "id": extra.pop("id", f"CODE-STUDIO-HANDOFF-{project}"),
        "project": project,
        "source_contract": planning_contract["id"],
        "source_contract_hash": planning_contract["contract_hash"],
        "context": context,
        "fixed_constraints": extra.pop("fixed_constraints", []),
        "open_questions": extra.pop("open_questions", []),
        **extra,
    }


def build_code_generator_handoff(
    project: str,
    planning_contract: dict,
    tasks: list[dict],
    gates: list[dict],
    **extra: object,
) -> dict:
    assert_handoff_allowed(planning_contract)
    source_design = extra.pop("source_design", None)
    payload = {
        "schema_version": 1,
        "id": extra.pop("id", f"CODE-GENERATOR-HANDOFF-{project}"),
        "project": project,
        "source_contract": planning_contract["id"],
        "source_contract_hash": planning_contract["contract_hash"],
        "tasks": tasks,
        "gates": gates,
        "evidence_expectations": extra.pop("evidence_expectations", []),
        **extra,
    }
    if source_design is not None:
        payload["source_design"] = source_design
    return payload
