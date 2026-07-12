from __future__ import annotations


def build_project_specific_requirements(project: str, requirements: list[dict], **extra: object) -> dict:
    return {
        "schema_version": 1,
        "id": extra.pop("id", f"PROJECT-REQS-{project}"),
        "status": "draft",
        "project": project,
        "requirements": requirements,
        **extra,
    }

