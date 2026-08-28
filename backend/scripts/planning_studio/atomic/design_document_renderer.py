from __future__ import annotations


def render_design_markdown(planning_contract: dict) -> str:
    sections = planning_contract.get("sections") or {}
    lines = [
        f"# Project Design: {planning_contract.get('project', '')}",
        "",
        "## Intent",
        str((sections.get("intent") or {}).get("summary", "")),
        "",
        "## Assurance",
        str(sections.get("assurance") or {}),
        "",
        "## Governance",
        str(sections.get("governance") or {}),
        "",
    ]
    return "\n".join(lines)


def build_design_document_manifest(project: str, planning_contract: dict, document_path: str, document_hash: str) -> dict:
    return {
        "schema_version": 1,
        "id": f"DESIGN-DOC-{project}",
        "project": project,
        "source_contract": planning_contract["id"],
        "source_contract_hash": planning_contract.get("contract_hash"),
        "document_path": document_path,
        "document_hash": document_hash,
        "sections_rendered": list((planning_contract.get("sections") or {}).keys()),
    }

