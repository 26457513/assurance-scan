from __future__ import annotations

from pathlib import Path

from planning_studio.storage import write_artifact


def save_questionnaire(root: Path, payload: dict) -> Path:
    return write_artifact(root, "project_design_questionnaire", payload)


def save_answers(root: Path, payload: dict) -> Path:
    return write_artifact(root, "project_design_answers", payload)

