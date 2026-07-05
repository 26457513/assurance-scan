#!/usr/bin/env python3
"""Graph data builder for D3 traceability graph."""
from __future__ import annotations

from typing import Any

def build_graph_data(catalog: Any) -> dict:
    """Build nodes + edges for the D3 graph from the FR catalog.

    MVP: structural view (FR → code → tests → compliance rows).
    Evidence status shown in framework tabs; graph focuses on structure.
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(node_id: str, node_type: str, label: str, **extra) -> dict:
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "type": node_type, "label": label, **extra}
        return nodes[node_id]

    def add_edge(source: str, target: str, edge_type: str) -> None:
        edge_key = f"{source}->{target}:{edge_type}"
        if not any(e.get("key") == edge_key for e in edges):
            edges.append({"source": source, "target": target, "type": edge_type, "key": edge_key})

    for req in catalog.requirements:
        if req.get("status") != "active":
            continue
        fr_id = f"fr:{req['id']}"
        fr_node = add_node(fr_id, "fr", req["title"], status=req.get("status", "active"),
                           fr_id=req["id"])

        # Code references
        for impl in req.get("implemented_by") or []:
            path = impl.get("path", "?")
            label = impl.get("label") or path
            code_id = f"code:{path}"
            add_node(code_id, "code", label)
            add_edge(fr_id, code_id, "implements")

        # Verified by (tests + scanners)
        for vb in req.get("verified_by") or []:
            vtype = vb.get("type", "")
            ref = vb.get("ref", "")
            if vtype == "scanner":
                node_id = f"scanner:{ref}"
                label = ref
            else:
                node_id = f"test:{ref}"
                label = ref
            add_node(node_id, vtype if vtype != "scanner" else "scanner", label)
            add_edge(fr_id, node_id, "verified_by")

        # Satisfies (compliance rows)
        for sat in req.get("satisfies") or []:
            fw = sat.get("framework", "?")
            row = sat.get("row", "?")
            row_id = f"{fw}:{row}"
            label = f"{fw} {row}"
            status = sat.get("status", "satisfied")
            add_node(row_id, "compliance", label, framework=fw, na=(status == "na"))
            add_edge(fr_id, row_id, "satisfies")

        # Evidence artifacts
        for ev in req.get("evidence") or []:
            ev_ref = ev.get("ref", "?")
            ev_type = ev.get("type", "manual")
            ev_id = f"evidence:{ev_ref}"
            add_node(ev_id, "evidence", ev_ref)
            add_edge(fr_id, ev_id, "evidenced_by")

    return {"nodes": list(nodes.values()), "edges": edges}



