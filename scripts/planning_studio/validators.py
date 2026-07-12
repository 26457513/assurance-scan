"""Planning Studio validation helpers."""
from __future__ import annotations

from pathlib import Path

from load_target_artifacts import TargetArtifactError, load_target_artifact


def validate_artifact(path: Path, kind: str, *, strict: bool = True) -> list[str]:
    try:
        load_target_artifact(path, kind, strict=strict)
    except TargetArtifactError as exc:
        return exc.errors
    return []


def assert_handoff_allowed(contract: dict) -> None:
    if contract.get("status") != "approved":
        raise ValueError("Planning handoff requires an approved resolved project planning contract")

