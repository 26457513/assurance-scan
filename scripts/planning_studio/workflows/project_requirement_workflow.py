from __future__ import annotations

from pathlib import Path

from planning_studio.storage import write_artifact


def save_project_specific_requirements(root: Path, payload: dict) -> Path:
    return write_artifact(root, "project_specific_requirements", payload)

