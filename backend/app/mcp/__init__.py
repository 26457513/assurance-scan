"""MCP-over-Streamable-HTTP endpoint.

Implements the Assurance Scan MCP tool surface used by the agent workflow:

  load_fr_catalog, start_scan, get_scan_status, cancel_scan, list_scans,
  get_findings, get_gap_analysis, add_waiver, revoke_waiver
"""
from app.mcp.server import build_mcp_server, mount_mcp_on_app

__all__ = ["build_mcp_server", "mount_mcp_on_app"]
