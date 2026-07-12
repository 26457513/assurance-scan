from __future__ import annotations


def build_repository_analysis_summary(project: str, source_repo: str, findings: list[dict], **extra: object) -> dict:
    return {
        "schema_version": 1,
        "id": extra.pop("id", f"REPO-ANALYSIS-{project}"),
        "project": project,
        "source_repo": source_repo,
        "source_artifacts": extra.pop("source_artifacts", []),
        "findings": findings,
        **extra,
    }

