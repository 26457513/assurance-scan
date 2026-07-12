from __future__ import annotations


def build_config_selection(project: str, selections: list[dict], **extra: object) -> dict:
    return {
        "schema_version": 1,
        "id": extra.pop("id", f"CONFIG-{project}"),
        "status": "draft",
        "project": project,
        "selections": selections,
        "unknowns": extra.pop("unknowns", []),
        "not_applicable": extra.pop("not_applicable", []),
        **extra,
    }

