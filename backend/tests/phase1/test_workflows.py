"""FR-WORKFLOWS tests.

Verifies the workflow loader and renderer: list_workflows returns metadata
for all workflow JSON files; get_workflow returns a single workflow with
parameter substitution applied.
"""
from __future__ import annotations

from app.modules.atomic.agent_workflow_catalog import get_workflow, list_workflows


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
