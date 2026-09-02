"""Tests for normalized GitHub Actions result persistence."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select as sa_select

from app.infrastructure.db.models import (
    Finding,
    Project,
    Run,
    ScanJob,
    ScannerArtifact,
    ScannerRun,
    SourceContext,
)
from app.infrastructure.db.repositories.source_contexts import SourceContextRepository
from app.modules.atomic.ingestion.result_persister._adapters import SqlAlchemyIngestPersistence
from app.modules.workflows.result_ingest import (
    ResolvedProject,
    build_github_inputs,
    github_run_id,
    ingest_result_bundle,
)


META = {
    "github_run_id": 32127508239,
    "github_repository_id": 987654,
    "repo": "26457513/doc2context",
    "conclusion": "success",
    "head_branch": "trial/pr-comment",
    "head_sha": "3" * 40,
    "run_url": "https://github.com/26457513/doc2context/actions/runs/32127508239",
    "started_at": datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc),
    "completed_at": datetime(2026, 8, 18, 12, 7, tzinfo=timezone.utc),
    "run_attempt": 1,
}


def _register_project(session) -> None:
    session.add(Project(
        id=123,
        tag="doc2context",
        local_path=None,
        github_repo="26457513/doc2context",
        github_repo_key="26457513/doc2context",
        github_repository_id=987654,
    ))


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
    _register_project(session)
    blobs = {
        "sarif": b"{}",
        "sbom": b"{}",
        "findings": json.dumps(_payload()).encode(),
    }
    envelope, bundle = build_github_inputs(
        ResolvedProject(123, "26457513/doc2context", 987654),
        META,
        _payload(),
        blobs,
    )
    status = await ingest_result_bundle(
        SqlAlchemyIngestPersistence(session), envelope, bundle
    )
    assert status == "ingested"
    assert github_run_id(987654, 32127508239, 1) == "gh-987654-32127508239-1"

    run = (await session.execute(sa_select(Run))).scalars().one()
    assert run.run_id == "gh-987654-32127508239-1"
    assert run.project_id == 123
    assert run.origin == "github-actions"
    assert run.repository_full_name_at_scan == "26457513/doc2context"
    assert run.working_tree_dirty is False
    assert run.status == "completed"
    assert run.git_branch == "trial/pr-comment"
    assert run.commit_sha == META["head_sha"]
    assert run.github_run_url == META["run_url"]

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
    _register_project(session)
    envelope, bundle = build_github_inputs(
        ResolvedProject(123, "26457513/doc2context", 987654),
        META,
        _payload(),
        {"results.sarif": b"{}"},
    )
    await ingest_result_bundle(SqlAlchemyIngestPersistence(session), envelope, bundle)
    status = await ingest_result_bundle(
        SqlAlchemyIngestPersistence(session), envelope, bundle
    )
    assert status == "exists"
    runs = (await session.execute(sa_select(Run))).scalars().all()
    findings = (await session.execute(sa_select(Finding))).scalars().all()
    assert len(runs) == 1
    assert len(findings) == 2


async def test_github_ingest_persists_finding_scoped_source_context(session) -> None:
    _register_project(session)
    payload = _payload()
    finding_keys = (
        "5f874412-d500-5c0c-a7f2-4758f022af4a",
        "dd880de8-c625-58d8-a00c-334611e5cdb0",
    )
    for finding, finding_key in zip(payload["findings"], finding_keys, strict=True):
        finding["finding_key"] = finding_key
    payload["source_contexts"] = [
        {
            "context_key": "8365422d-c67f-5135-a7ef-ea4811d7bff5",
            "finding_keys": [finding_keys[0]],
            "available": True,
            "provider": "snapshot",
            "path": "src/app.py",
            "window_start": 8,
            "window_end": 10,
            "highlight_start": 10,
            "highlight_end": 10,
            "highlight_truncated": False,
            "lines": [
                {"number": number, "text": f"line {number}", "truncated": False}
                for number in range(8, 11)
            ],
            "source_hash": "a" * 64,
            "redaction_version": 1,
            "redaction_changed": False,
        },
        {
            "context_key": "5c54bf67-703f-5b96-ab9e-1242fe48001c",
            "finding_keys": [finding_keys[1]],
            "available": False,
            "provider": "snapshot",
            "path": "src/app.py",
            "redaction_version": 1,
            "redaction_changed": False,
            "unavailable_reason": "file_too_large",
        },
    ]
    envelope, bundle = build_github_inputs(
        ResolvedProject(123, "26457513/doc2context", 987654),
        META,
        payload,
    )

    await ingest_result_bundle(SqlAlchemyIngestPersistence(session), envelope, bundle)

    findings = (await session.execute(sa_select(Finding).order_by(Finding.id))).scalars().all()
    assert [finding.finding_key for finding in findings] == list(finding_keys)
    contexts = (await session.execute(sa_select(SourceContext))).scalars().all()
    assert len(contexts) == 2
    assert {context.provider for context in contexts} == {"snapshot"}
    repository = SourceContextRepository(session)
    assert await repository.get_for_finding("gh-987654-32127508239-1", findings[0].id) is not None
    assert await repository.get_for_finding("gh-987654-32127508239-1", findings[1].id) is not None


async def test_ingest_failed_run_without_payload(session) -> None:
    _register_project(session)
    failed_meta = {**META, "conclusion": "failure"}
    envelope, bundle = build_github_inputs(
        ResolvedProject(123, "26457513/doc2context", 987654),
        failed_meta,
        None,
    )
    status = await ingest_result_bundle(
        SqlAlchemyIngestPersistence(session), envelope, bundle
    )
    assert status == "ingested"
    run = (await session.execute(sa_select(Run))).scalars().one()
    assert run.status == "failed"
    assert run.error_message == "GitHub workflow produced no scan results"
    assert (await session.execute(sa_select(Finding))).scalars().first() is None


async def test_valid_results_complete_even_when_github_workflow_failed(session) -> None:
    _register_project(session)
    failed_meta = {**META, "conclusion": "failure"}
    envelope, bundle = build_github_inputs(
        ResolvedProject(123, "26457513/doc2context", 987654),
        failed_meta,
        _payload(),
    )
    await ingest_result_bundle(SqlAlchemyIngestPersistence(session), envelope, bundle)
    run = (await session.execute(sa_select(Run))).scalars().one()
    assert run.status == "completed"
    assert run.error_message is None
