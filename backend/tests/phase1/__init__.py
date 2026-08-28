"""Tests for the Phase 1 server modules.

Scope:
  - Catalogue loader + v1→v2 migration
  - State machine + evidence matcher
  - Scanner parsers (SARIF/JSON)
  - MCP tools (in-process)

These tests run without docker — they exercise pure Python logic. The
in-process DB is an in-memory SQLite that's reset per test.
"""
