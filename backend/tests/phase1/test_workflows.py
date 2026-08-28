"""FR-WORKFLOWS tests.

Verifies the workflow loader and renderer: list_workflows returns metadata
for all workflow JSON files; get_workflow returns a single workflow with
parameter substitution applied.
"""
from __future__ import annotations

import json
import re

from app.modules.atomic.agent_workflow_catalog import (
    WORKFLOWS_DIR,
    get_workflow,
    list_workflows,
)


_SOURCE_WORKFLOWS = {
    "author-fr-catalogue",
    "code-finding-fix",
    "code-fr-test",
    "scan-project",
    "setup-project",
}
_SIMPLE_PLACEHOLDER = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def test_list_workflows_returns_known_workflows() -> None:
    workflows = list_workflows()
    names = {w["name"] for w in workflows}
    # These ship with the project; any of them being present proves the loader
    # is finding and parsing the workflow JSON files.
    expected_subset = {"setup-project", "scan-project"}
    assert expected_subset.issubset(names), f"missing workflows: {expected_subset - names}"
    # Each workflow has the metadata fields the MCP tool surfaces.
    for w in workflows:
        assert "name" in w and isinstance(w["name"], str) and w["name"]
        assert "description" in w and isinstance(w["description"], str)
        assert "parameters" in w and isinstance(w["parameters"], list)


def test_get_workflow_renders_known_parameter() -> None:
    # "code-fr-test" has an `fr_id` parameter used in its prompt body.
    rendered = get_workflow("code-fr-test", {"fr_id": "FR-WIDGET"})
    assert rendered["name"] == "code-fr-test"
    assert "FR-WIDGET" in rendered["prompt"]
    # The original placeholder should be gone now that we supplied a value.
    assert "{{fr_id}}" not in rendered["prompt"]
    assert rendered["provided_parameters"] == {"fr_id": "FR-WIDGET"}


def test_get_workflow_leaves_unknown_parameters_as_placeholders() -> None:
    rendered = get_workflow("code-fr-test", {})
    # We didn't supply fr_id, so the placeholder must remain for the agent to fill in.
    assert "{{fr_id}}" in rendered["prompt"]
    assert rendered["provided_parameters"] == {}


def test_get_workflow_unknown_name_returns_error_envelope() -> None:
    rendered = get_workflow("does-not-exist")
    assert rendered.get("error") == "not_found"
    assert rendered["name"] == "does-not-exist"
    # The error envelope must list available workflows so the agent can self-correct.
    assert isinstance(rendered.get("available"), list) and rendered["available"]


def test_old_workflow_names_still_resolve() -> None:
    """Pre-standardisation names alias to the new canonical ones."""
    from app.modules.atomic.agent_workflow_catalog import _ALIASES

    for old, new in _ALIASES.items():
        rendered = get_workflow(old, {})
        assert rendered["name"] == new, f"{old} should resolve to {new}"


def test_workflow_documents_follow_project_id_contract() -> None:
    """Project identity and source location must remain distinct contracts."""
    paths = sorted(WORKFLOWS_DIR.glob("*.json"))
    assert paths
    for path in paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert set(doc) == {"name", "description", "parameters", "prompt"}, path
        assert doc["name"] == path.stem
        assert isinstance(doc["description"], str) and doc["description"]
        assert isinstance(doc["prompt"], str) and doc["prompt"]

        parameters = doc["parameters"]
        assert isinstance(parameters, list) and parameters
        names = [parameter["name"] for parameter in parameters]
        assert len(names) == len(set(names)), path
        assert "project_id" in names, path
        assert "project_path" not in names, path
        for parameter in parameters:
            assert set(parameter) <= {"name", "description", "default"}, path
            assert isinstance(parameter["name"], str) and parameter["name"]
            assert isinstance(parameter["description"], str) and parameter["description"]

        serialized = json.dumps(doc)
        assert "project_path" not in serialized, path
        assert "github:" not in serialized, path
        placeholders = set(_SIMPLE_PLACEHOLDER.findall(doc["prompt"]))
        assert placeholders <= set(names), (path, placeholders - set(names))

        uses_checkout = doc["name"] in _SOURCE_WORKFLOWS
        assert ("checkout_path" in names) is uses_checkout, path
        assert ("{{checkout_path}}" in doc["prompt"]) is uses_checkout, path


def test_rendered_workflow_keeps_id_and_checkout_separate() -> None:
    rendered = get_workflow(
        "code-finding-fix",
        {
            "project_id": "42",
            "checkout_path": "/workspace/widget",
            "fr_id": "FR-WIDGET",
        },
    )
    prompt = rendered["prompt"]
    assert "bootstrap` with `project_id=42`" in prompt
    assert "start_scan` with `project_id=42`" in prompt
    assert "under /workspace/widget" in prompt
    assert "project_path" not in prompt
