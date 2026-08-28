from __future__ import annotations


def build_answers(project: str, questionnaire: str, answers: list[dict], **extra: object) -> dict:
    return {
        "schema_version": 1,
        "id": extra.pop("id", f"ANSWERS-{project}"),
        "status": "draft",
        "project": project,
        "questionnaire": questionnaire,
        "answers": answers,
        "unknowns": extra.pop("unknowns", []),
        "assumptions": extra.pop("assumptions", []),
        **extra,
    }

