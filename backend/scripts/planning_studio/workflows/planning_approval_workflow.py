from __future__ import annotations

from pathlib import Path

from planning_studio.atomic.planning_contract_resolver import recompute_contract_hash
from planning_studio.storage import write_artifact


def approve_resolved_contract(root: Path, payload: dict) -> Path:
    approved = dict(payload)
    approved["status"] = "approved"
    approved = recompute_contract_hash(approved)
    return write_artifact(root, "resolved_project_planning_contract", approved)
