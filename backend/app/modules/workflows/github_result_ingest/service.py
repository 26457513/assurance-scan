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
    github_run_id = str((payload or {}).get("github_run_id") or meta["github_run_id"])
    run_id = f"gh-{github_run_id}"
    if await run_exists(persistence, run_id):
        return "exists"

    repo = (payload or {}).get("repo") or meta["repo"]
    failed = meta.get("conclusion") == "failure"
    record = RunRecord(
        run_id=run_id,
        project_path=f"github:{repo}",
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
        commit_sha=(payload or {}).get("commit") or meta.get("head_sha"),
        git_branch=(payload or {}).get("branch") or meta.get("head_branch"),
        error_message="GitHub workflow run failed" if failed else None,
        findings_json=json.dumps(payload) if payload is not None else None,
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
