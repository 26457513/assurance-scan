"""Workflow for ingesting GitHub Actions result bundles."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.modules.atomic.ingestion.bundle_validator import validate_bundle
from app.modules.atomic.ingestion.finding_normalizer import normalize_findings
from app.modules.atomic.ingestion.idempotency_guard import run_exists
from app.modules.atomic.ingestion.result_persister import persist_result_bundle
from app.modules.shared.contracts.ingest import IngestStatus, RunRecord

from .models import IngestPersistencePort


log = logging.getLogger(__name__)


def ci_run_id(payload: dict[str, Any]) -> str:
    """Return the stable run identifier used by the existing GitHub poller."""

    return f"gh-{payload['github_run_id']}"


async def ingest_ci_run(
    persistence: IngestPersistencePort,
    payload: dict[str, Any] | None,
    meta: dict[str, Any],
    blobs: dict[str, bytes] | None = None,
) -> IngestStatus:
    """Create one CI run from a findings payload and GitHub run metadata."""

    bundle = validate_bundle(payload, meta, blobs)
    github_run_id = str(meta["github_run_id"])
    run_id = f"gh-{github_run_id}"
    if await run_exists(persistence, run_id):
        return "exists"

    repo = str(meta["repo"])
    if payload is not None:
        payload_run_id = payload.get("github_run_id")
        if payload_run_id is not None and str(payload_run_id) != github_run_id:
            raise ValueError("result bundle GitHub run ID does not match poller metadata")
        payload_repo = payload.get("repo")
        if payload_repo is not None and str(payload_repo).casefold() != repo.casefold():
            raise ValueError("result bundle repository does not match poller metadata")
    project = await persistence.resolve_github_project(repo)
    if project is None:
        raise ValueError(f"GitHub repository is not a visible registered project: {repo}")
    failed = meta.get("conclusion") == "failure"
    scanned_commit = (payload or {}).get("commit") or meta.get("head_sha")
    git_object_format = (
        "sha1" if scanned_commit and len(str(scanned_commit)) == 40
        else "sha256" if scanned_commit and len(str(scanned_commit)) == 64
        else None
    )
    record = RunRecord(
        run_id=run_id,
        project_id=project.project_id,
        origin="github-actions",
        options_json=json.dumps({
            "source": "github-actions",
            "repo": repo,
            "run_url": meta.get("run_url") or (payload or {}).get("run_url"),
            "run_number": meta.get("run_number"),
            "event": meta.get("event"),
            "actor": meta.get("actor"),
            "display_title": meta.get("display_title"),
        }),
        status="failed" if failed else "completed",
        started_at=meta.get("started_at"),
        completed_at=meta.get("completed_at"),
        commit_sha=scanned_commit,
        git_branch=meta.get("head_branch") or (payload or {}).get("branch"),
        error_message="GitHub workflow run failed" if failed else None,
        findings_json=json.dumps(payload) if payload is not None else None,
        repository_full_name_at_scan=project.repository,
        git_object_format=git_object_format,
        working_tree_dirty=False,
        github_run_id=int(github_run_id),
        github_run_number=meta.get("run_number"),
        github_run_attempt=meta.get("run_attempt"),
        github_run_url=meta.get("run_url"),
        github_event=meta.get("event"),
        github_actor=meta.get("actor"),
        github_head_sha=meta.get("head_sha"),
    )
    findings = normalize_findings(run_id, (payload or {}).get("findings", []))
    await persist_result_bundle(persistence, record, bundle, findings)

    log.info(
        "ingested CI run %s (%s, %d findings)",
        run_id,
        record.status,
        len(payload.get("findings", [])) if payload else 0,
    )
    return "ingested"
