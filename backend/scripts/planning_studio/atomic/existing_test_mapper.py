from __future__ import annotations


def build_existing_evidence_mapping_proposal(project: str, proposals: list[dict], **extra: object) -> dict:
    return {
        "schema_version": 1,
        "id": extra.pop("id", f"EXISTING-EVIDENCE-{project}"),
        "status": "review_required",
        "project": project,
        "proposals": proposals,
        **extra,
    }

