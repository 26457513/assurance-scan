"""Ingest a CI findings.json payload into the DB (phase 2, pull model).

CI runs land as `run_id = "gh-{github_run_id}"` on
`project_path = "github:{owner}/{repo}"` — no migrations; the projects
registry derives them automatically.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import Run, ScanJob
from server.db.repositories.findings import FindingRepository
from server.db.repositories.runs import RunRepository
from server.db.repositories.scanner_artifacts import ScannerArtifactRepository
from server.db.repositories.scanner_runs import ScannerRunRepository


log = logging.getLogger(__name__)

# Artifact blobs ride on synthetic scanner-run rows (one artifact per
# scanner_run — the schema is 1:1), so each blob gets its own row.
BLOB_ARTIFACTS: tuple[tuple[str, str, str], ...] = (
    # (suffix, artifact kind, description)
    ("sarif", "sarif", "assurance-scan/sarif"),
    ("sbom", "cyclonedx-json", "assurance-scan/sbom"),
    ("findings", "json", "assurance-scan/findings"),
)


def ci_run_id(payload: dict[str, Any]) -> str:
    return f"gh-{payload['github_run_id']}"


async def ingest_ci_run(
    session: AsyncSession,
    payload: dict[str, Any] | None,
    meta: dict[str, Any],
    blobs: dict[str, bytes] | None = None,
) -> str:
    """Create one CI run from a findings.json payload + run metadata.

    Returns "ingested" or "exists". `meta` comes from the GitHub runs API
    (conclusion, head_branch, head_sha, created_at, updated_at) and is
    authoritative for status/timestamps; `payload` may be None for failed
    runs whose artifact is missing.
    """
    github_run_id = str((payload or {}).get("github_run_id") or meta["github_run_id"])
    run_id = f"gh-{github_run_id}"
    runs = RunRepository(session)
    if await runs.get(run_id) is not None:
        return "exists"

    repo = (payload or {}).get("repo") or meta["repo"]
    project_path = f"github:{repo}"
    failed = meta.get("conclusion") == "failure"

    run = Run(
        run_id=run_id,
        project_path=project_path,
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
        # Payload-first: remote-runner runs report the TARGET repo's
        # branch/commit; meta would carry the runner repo's.
        commit_sha=(payload or {}).get("commit") or meta.get("head_sha"),
        git_branch=(payload or {}).get("branch") or meta.get("head_branch"),
        error_message="GitHub workflow run failed" if failed else None,
        findings_json=json.dumps(payload) if payload is not None else None,
    )
    session.add(run)
    session.add(ScanJob(
        run_id=run_id,
        state="failed" if failed else "completed",
        queued_at=meta.get("started_at"),
        started_at=meta.get("started_at"),
        completed_at=meta.get("completed_at"),
        error_message=run.error_message,
    ))

    if payload is not None:
        scanner_runs = ScannerRunRepository(session)
        artifacts = ScannerArtifactRepository(session)

        for kind, st in sorted(payload.get("scanner_status", {}).items()):
            sr = await scanner_runs.create(run_id, kind)
            if st == "ok":
                await scanner_runs.mark_completed(sr.id)
            else:
                await scanner_runs.mark_failed(sr.id, st)

        blobs = blobs or {}
        blob_inputs = {
            "sarif": blobs.get("sarif"),
            "sbom": blobs.get("sbom"),
            "findings": blobs.get("findings"),
        }
        for suffix, artifact_kind, _desc in BLOB_ARTIFACTS:
            content = blob_inputs[suffix]
            if content is None:
                continue
            sr = await scanner_runs.create(run_id, f"assurance-scan/{suffix}")
            await scanner_runs.mark_completed(sr.id)
            await artifacts.store(scanner_run_id=sr.id, kind=artifact_kind, content=content)

        rows = [
            {
                "run_id": run_id,
                "scanner_kind": f["scanner"],
                "rule_id": f.get("rule_id"),
                "severity": f.get("severity"),
                "file_path": f.get("file_path"),
                "line_start": f.get("line_start"),
                "line_end": f.get("line_end"),
                "message": f.get("message") or "",
                "theme": f.get("theme"),
                "fix_strategy": f.get("fix_strategy"),
                "compliance_tags": f.get("compliance_tags") or [],
            }
            for f in payload.get("findings", [])
        ]
        if rows:
            await FindingRepository(session).bulk_insert(rows)

    await session.commit()
    log.info(
        "ingested CI run %s (%s, %d findings)",
        run_id, run.status, len(payload.get("findings", [])) if payload else 0,
    )
    return "ingested"
