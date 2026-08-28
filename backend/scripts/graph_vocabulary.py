#!/usr/bin/env python3
"""Shared runtime vocabulary for assurance graph artifacts.

The JSON schemas are the contract. This module is the small Python bridge that
lets graph builders, dashboard projection, and validators consume that contract
without duplicating enum literals.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "resources" / "schemas"
DEFS_SCHEMA = SCHEMA_DIR / "defs.schema.json"

GRAPH_NODE_ALIASES = {
    "compliance": "ruleset_row",
    "code": "file",
    "scanner": "scanner_rule",
    "unit": "tbt",
    "integration": "tbt",
    "e2e": "tbt",
    "load": "tbt",
    "test": "tbt",
    "manual": "evidence",
    "document": "evidence",
}

GRAPH_EDGE_ALIASES = {
    "verified_by": "requires",
    "requires_test": "requires",
    "requires_scanner": "requires",
    "requires_manual": "requires",
    "requires_fr": "requires",
    "requires_tbt": "requires",
    "requires_approval": "requires",
    "requires_document": "requires",
    "requires_manual_note": "requires",
    "requires_screenshot": "requires",
    "requires_role": "requires",
    "evidenced_by": "evidences",
    "supported_by": "evidences",
    "contains_gate": "requires",
    "has_criterion": "requires",
    "discovers": "maps_to",
    "contains_test": "maps_to",
    "packaged_as": "maps_to",
}


@lru_cache(maxsize=1)
def shared_defs() -> dict[str, Any]:
    return json.loads(DEFS_SCHEMA.read_text())


def shared_enum(name: str) -> set[str]:
    values = shared_defs().get("$defs", {}).get(name, {}).get("enum", [])
    return {str(value) for value in values}


GRAPH_NODE_TYPES = shared_enum("graph_node_type")
GRAPH_EDGE_TYPES = shared_enum("graph_edge_type")
GRAPH_RESPONSIBILITIES = shared_enum("graph_responsibility")


def normalise_graph_node_type(raw_type: Any) -> str:
    value = str(raw_type or "evidence")
    return GRAPH_NODE_ALIASES.get(value, value if value in GRAPH_NODE_TYPES else "evidence")


def normalise_graph_edge_type(raw_type: Any) -> str:
    value = str(raw_type or "requires")
    if value in GRAPH_RESPONSIBILITIES:
        return "assigned_to"
    return GRAPH_EDGE_ALIASES.get(value, value if value in GRAPH_EDGE_TYPES else "requires")


def graph_edge_responsibility(raw_type: Any, explicit: Any = None) -> str | None:
    raw_value = str(raw_type or "")
    explicit_value = str(explicit or "")
    if raw_value in GRAPH_RESPONSIBILITIES:
        return raw_value
    if explicit_value in GRAPH_RESPONSIBILITIES:
        return explicit_value
    return None
