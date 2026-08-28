from __future__ import annotations

from pathlib import Path

from planning_studio.storage import read_artifact, write_artifact


def save_session_artifact(root: Path, kind: str, payload: dict) -> Path:
    return write_artifact(root, kind, payload)


def load_session_artifact(root: Path, kind: str) -> dict:
    return read_artifact(root, kind)

