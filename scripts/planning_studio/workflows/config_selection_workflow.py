from __future__ import annotations

from pathlib import Path

from planning_studio.storage import write_artifact


def save_config_selection(root: Path, payload: dict) -> Path:
    if payload.get("status") == "approved":
        raise ValueError("Config selection drafts are approved only through the planning approval workflow")
    return write_artifact(root, "project_config_selection", payload)

