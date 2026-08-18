"""FR-MCP-SERVER tests.

The MCP server (mounted at /mcp) exposes ~12 tools that agents use to drive
scans, fetch findings, manage waivers, and request workflows. These tests
verify the tool surface: that build_mcp_server registers every expected
tool, and that the tool list matches what's documented in FR-MCP-SERVER's
description.

Calling each tool end-to-end would duplicate the unit tests for the underlying
functions (workflows tested in test_workflows, findings in test_findings_persist,
etc.). Here we verify the REGISTRATION and SHAPE — the tool surface contract.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI

from server.mcp import build_mcp_server


@pytest.fixture
def mcp_server():
    """Build the MCP server against a minimal FastAPI shell."""
    app = FastAPI()
    return build_mcp_server(app)


def _tool_names(mcp_server) -> set[str]:
    """Pull the registered tool names out of the FastMCP server's tool registry."""
    # FastMCP exposes registered tools via `_tool_manager` (private) — but the
    # public API for listing tools is the same one the MCP protocol uses.
    # We use the private attribute defensively; the test asserts a stable shape.
    tm = mcp_server._tool_manager
    return set(tm._tools.keys())


def test_mcp_server_builds_without_error() -> None:
    """The MCP server must build cleanly when mounted on a FastAPI app."""
    app = FastAPI()
    mcp = build_mcp_server(app)
    assert mcp is not None


def test_expected_tools_are_registered(mcp_server) -> None:
    """All 12 documented tools must be present in the registry."""
    names = _tool_names(mcp_server)
    expected = {
        "load_fr_catalog",
        "start_scan",
        "get_scan_status",
        "cancel_scan",
        "list_scans",
        "get_findings",
        "get_gap_analysis",
        "add_waiver",
        "revoke_waiver",
        "list_workflows",
        "get_workflow",
        "bootstrap",
        "save_catalogue",
        "save_mapping",
    }
    missing = expected - names
    assert not missing, f"missing MCP tools: {missing}"


def test_no_unexpected_extra_tools_registered(mcp_server) -> None:
    """A new tool is fine — but flag it here so the catalogue stays in sync."""
    names = _tool_names(mcp_server)
    known = {
        "load_fr_catalog",
        "start_scan",
        "get_scan_status",
        "cancel_scan",
        "list_scans",
        "get_findings",
        "get_gap_analysis",
        "add_waiver",
        "revoke_waiver",
        "list_workflows",
        "get_workflow",
        "bootstrap",
        "save_catalogue",
        "save_mapping",
    }
    extras = names - known
    # If you added a tool, add it to `known` above and to FR-MCP-SERVER's
    # description in the catalogue.
    assert not extras, (
        f"new MCP tools registered — update FR-MCP-SERVER count + this test: {extras}"
    )
