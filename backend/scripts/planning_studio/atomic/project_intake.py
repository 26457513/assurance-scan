from __future__ import annotations


def build_project_intake(project: str, mode: str, intent: str, **extra: object) -> dict:
    return {
        "schema_version": 1,
        "id": extra.pop("id", f"INTAKE-{project}"),
        "status": "draft",
        "project": project,
        "mode": mode,
        "intent": intent,
        **extra,
    }

