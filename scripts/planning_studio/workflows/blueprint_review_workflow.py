from __future__ import annotations

from pathlib import Path

from planning_studio.storage import write_artifact


def save_blueprint_proposal(root: Path, payload: dict) -> Path:
    return write_artifact(root, "blueprint_selection_proposal", payload)


def save_blueprint_decisions(root: Path, payload: dict) -> Path:
    return write_artifact(root, "blueprint_decision_log", payload)

