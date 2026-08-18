"""Tests for CI-run ingest (phase 2 pull model)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select as sa_select

from server.ci_ingest import ci_run_id, ingest_ci_run
from server.db.models import Finding, Run, ScanJob, ScannerArtifact, ScannerRun


META = {
    "github_run_id": 32127508239,
    "repo": "26457513/doc2context",
    "conclusion": "success",
    "head_branch": "trial/pr-comment",
    "head_sha": "334865b" * 5,
    "run_url": "https://github.com/26457513/doc2context/actions/runs/32127508239",
    "started_at": datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc),
    "completed_at": datetime(2026, 8, 18, 12, 7, tzinfo=timezone.utc),
}


def _payload() -> dict:
    return {
        "schema_version": 1,
        "source": "github-actions",
        "repo": "26457513/doc2context",
        "github_run_id": 32127508239,
        "run_url": META["run_url"],
        "branch": "trial/pr-comment",
        "commit": META["head_sha"],
        "scanner_status": {"semgrep": "ok", "gitleaks": "exit=1"},
        "durations": {"semgrep": 12.3},
        "summary": {"total": 2, "by_severity": {"HIGH": 2}, "by_scanner": {"semgrep": 2}},
        "findings": [
            {
                "id": "F-001", "scanner": "semgrep", "rule_id": "rule-a",
                "severity": "HIGH", "file_path": "src/app.py", "line_start": 10,
                "line_end": 10, "message": "bad", "theme": None,
                "fix_strategy": None, "compliance_tags": [],
            },
            {
                "id": "F-002", "scanner": "semgrep", "rule_id": "rule-a",
                "severity": "HIGH", "file_path": "src/app.py", "line_start": 20,
                "line_end": 20, "message": "worse", "theme": None,
                "fix_strategy": None, "compliance_tags": [],
            },
        ],
    }


async def test_ingest_creates_run_findings_scanner_runs_and_blobs(session) -> None:
    blobs = {
        "sarif": b"{}",
        "sbom": b"{}",
        "findings": json.dumps(_payload()).encode(),
    }
    status = await ingest_ci_run(session, _payload(), META, blobs)
    assert status == "ingested"
    assert ci_run_id(_payload()) == "gh-32127508239"

    run = (await session.execute(sa_select(Run))).scalars().one()
    assert run.run_id == "gh-32127508239"
    assert run.project_path == "github:26457513/doc2context"
    assert run.status == "completed"
    assert run.git_branch == "trial/pr-comment"
    assert run.commit_sha == META["head_sha"]
    assert json.loads(run.options_json)["run_url"] == META["run_url"]

    job = (await session.execute(sa_select(ScanJob))).scalars().one()
    assert job.state == "completed"

    findings = (await session.execute(sa_select(Finding))).scalars().all()
    assert len(findings) == 2
    assert findings[0].scanner_kind == "semgrep"

    scanner_runs = (await session.execute(sa_select(ScannerRun))).scalars().all()
    kinds = {sr.scanner_kind: sr.status for sr in scanner_runs}
    assert kinds["semgrep"] == "completed"
    assert kinds["gitleaks"] == "failed"
    # One synthetic row per stored blob.
    artifacts = (await session.execute(sa_select(ScannerArtifact))).scalars().all()
    assert len(artifacts) == 3


async def test_ingest_is_idempotent(session) -> None:
    await ingest_ci_run(session, _payload(), META, {"sarif": b"{}"})
    status = await ingest_ci_run(session, _payload(), META, {"sarif": b"{}"})
    assert status == "exists"
    runs = (await session.execute(sa_select(Run))).scalars().all()
    findings = (await session.execute(sa_select(Finding))).scalars().all()
    assert len(runs) == 1
    assert len(findings) == 2


async def test_ingest_failed_run_without_payload(session) -> None:
    failed_meta = {**META, "conclusion": "failure"}
    status = await ingest_ci_run(session, None, failed_meta)
    assert status == "ingested"
    run = (await session.execute(sa_select(Run))).scalars().one()
    assert run.status == "failed"
    assert run.error_message == "GitHub workflow run failed"
    assert (await session.execute(sa_select(Finding))).scalars().first() is None
