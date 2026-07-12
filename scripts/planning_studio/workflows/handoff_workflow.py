from __future__ import annotations

from pathlib import Path

from planning_studio.storage import write_artifact
from planning_studio.validators import assert_handoff_allowed


def publish_code_studio_handoff(root: Path, contract: dict, payload: dict) -> Path:
    assert_handoff_allowed(contract)
    return write_artifact(root, "code_studio_handoff_pack", payload)


def publish_code_generator_handoff(root: Path, contract: dict, payload: dict) -> Path:
    assert_handoff_allowed(contract)
    return write_artifact(root, "code_generator_handoff_pack", payload)

