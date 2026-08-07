"""Workflow loader and renderer.

Workflows are templated agent prompts stored as JSON files in
`data/workflows/`. The agent fetches them via the
`list_workflows` and `get_workflow` MCP tools, so the user doesn't have
to remember exact prompt text.

Parameter substitution uses `{{name}}` placeholders in the prompt body.
Unknown parameters are left as-is (so the agent can fill them).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


WORKFLOWS_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "workflows"
)


@dataclass(frozen=True)
class Workflow:
    """One workflow definition."""

    name: str
    description: str
    parameters: list[dict[str, Any]]
    prompt_template: str


_PARAM_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def list_workflows() -> list[dict[str, Any]]:
    """Return metadata for every workflow in the workflows dir."""
    out: list[dict[str, Any]] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            out.append({
                "name": doc["name"],
                "description": doc.get("description", ""),
                "parameters": doc.get("parameters", []),
            })
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            log.warning("could not load workflow %s: %s", path, exc)
    return out


def get_workflow(name: str, parameters: dict[str, str] | None = None) -> dict[str, Any]:
    """Return a single workflow with its prompt rendered with parameters.

    Missing parameters are left as `{{name}}` placeholders so the agent
    can fill them in by reading the conversation context.
    """
    path = WORKFLOWS_DIR / f"{name}.json"
    if not path.exists():
        return {"error": "not_found", "name": name, "available": [w["name"] for w in list_workflows()]}

    doc = json.loads(path.read_text(encoding="utf-8"))
    prompt = doc.get("prompt", "")
    params = parameters or {}

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        return params.get(key, match.group(0))

    rendered = _PARAM_RE.sub(_sub, prompt)

    return {
        "name": doc["name"],
        "description": doc.get("description", ""),
        "parameters": doc.get("parameters", []),
        "provided_parameters": params,
        "prompt": rendered,
    }
