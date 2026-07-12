from __future__ import annotations


def build_questionnaire(project: str, questions: list[dict], **extra: object) -> dict:
    return {
        "schema_version": 1,
        "id": extra.pop("id", f"QUESTIONNAIRE-{project}"),
        "status": "draft",
        "project": project,
        "questions": questions,
        **extra,
    }

