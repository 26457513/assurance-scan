"""Focused contracts and transaction tests for source-neutral ingestion."""
from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, cast

import pytest

from app.modules.atomic.ingestion.finding_normalizer import normalize_findings
from app.modules.atomic.ingestion.result_persister import persist_result_bundle
from app.modules.shared.contracts.ingest import (
    BLOB_ARTIFACTS,
    LocalIngestEnvelope,
    ResolvedProject,
    ResultBundle,
    RunRecord,
    ScannerResult,
)
from app.modules.workflows.result_ingest import (
    build_local_result_bundle,
    github_run_id,
    ingest_result_bundle,
)


def test_source_neutral_workflow_and_blob_contract_are_public() -> None:
    assert github_run_id(42) == "gh-42"
    assert BLOB_ARTIFACTS == (
        ("sarif", "sarif", "assurance-scan/sarif"),
        ("sbom", "cyclonedx-json", "assurance-scan/sbom"),
        ("findings", "json", "assurance-scan/findings"),
    )


def test_local_bundle_contains_scanner_output_only() -> None:
    document = {
        "schema_version": 1,
        "scanners": [{
            "kind": "semgrep",
            "status": "completed",
            "duration_ms": 12,
            "image": "semgrep/semgrep@sha256:" + "a" * 64,
            "tool_version": "1.0",
            "database_version": None,
            "error_code": None,
        }],
        "findings": [],
    }
    bundle = build_local_result_bundle(document, {"sarif": b"{}"})
    assert bundle.schema_version == 1
    assert bundle.scanners[0].image_digest == "sha256:" + "a" * 64
    assert not hasattr(bundle, "origin")
    assert not hasattr(bundle, "metadata")


def test_finding_normalizer_preserves_defaults_and_fields() -> None:
    rows = normalize_findings(
        "local-42",
        [cast(Any, {
            "scanner": "semgrep",
            "severity": "HIGH",
            "message": None,
            "compliance_tags": None,
        })],
    )
    assert rows == [{
        "run_id": "local-42",
        "scanner_kind": "semgrep",
        "rule_id": None,
        "severity": "HIGH",
        "file_path": None,
        "line_start": None,
        "line_end": None,
        "message": "",
        "theme": None,
        "fix_strategy": None,
        "compliance_tags": [],
    }]


class RecordingPersistence:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.events: list[tuple[Any, ...]] = []
        self.artifacts: list[bytes] = []
        self.findings: list[dict[str, Any]] = []

    async def get(self, run_id: str) -> object | None:
        self.events.append(("get", run_id))
        return None

    async def add_run(self, record: RunRecord) -> None:
        self.events.append(("run", record.run_id, record.origin))

    async def add_scan_job(self, record: RunRecord) -> None:
        self.events.append(("job", record.run_id))

    async def create_scanner_run(self, run_id: str, result: ScannerResult) -> int:
        self.events.append(("scanner", run_id, result.kind, result.status))
        return len(self.events)

    async def mark_scanner_completed(self, scanner_run_id: int) -> None:
        self.events.append(("completed", scanner_run_id))

    async def mark_scanner_failed(self, scanner_run_id: int, error: str) -> None:
        self.events.append(("failed", scanner_run_id, error))

    async def mark_scanner_skipped(self, scanner_run_id: int, reason: str | None) -> None:
        self.events.append(("skipped", scanner_run_id, reason))

    async def store_artifact(
        self, scanner_run_id: int, artifact_kind: str, content: bytes
    ) -> None:
        self.events.append(("artifact", scanner_run_id, artifact_kind))
        self.artifacts.append(content)

    async def insert_findings(self, findings: Sequence[dict[str, Any]]) -> None:
        self.events.append(("findings", len(findings)))
        self.findings.extend(findings)
        if self.fail_at == "findings":
            raise RuntimeError("injected persistence failure")

    async def before_commit(self, run_id: str) -> None:
        self.events.append(("before_commit", run_id))
        if self.fail_at == "before_commit":
            raise RuntimeError("injected finalization failure")

    async def commit(self) -> None:
        self.events.append(("commit",))

    async def rollback(self) -> None:
        self.events.append(("rollback",))


def _record() -> RunRecord:
    return RunRecord(
        run_id="local-42",
        project_id=42,
        origin="local",
        options_json="{}",
        status="completed",
        started_at=None,
        completed_at=None,
        commit_sha="a" * 40,
        git_branch="main",
        error_message=None,
        findings_json="{}",
    )


async def test_result_persister_stages_claim_then_commits_once() -> None:
    persistence = RecordingPersistence()
    bundle = ResultBundle(
        schema_version=1,
        scanners=(ScannerResult("semgrep", "completed"),),
        artifacts={"sarif": b"{}"},
    )
    await persist_result_bundle(persistence, _record(), bundle, [{"run_id": "local-42"}])
    assert persistence.events[-2:] == [("before_commit", "local-42"), ("commit",)]
    assert ("rollback",) not in persistence.events


@pytest.mark.parametrize("fail_at", ["findings", "before_commit"])
async def test_result_persister_rolls_back_every_partial_graph(fail_at: str) -> None:
    persistence = RecordingPersistence(fail_at=fail_at)
    bundle = ResultBundle(
        schema_version=1,
        scanners=(ScannerResult("semgrep", "completed"),),
        findings=({"scanner": "semgrep", "message": "bad"},),
    )
    with pytest.raises(RuntimeError, match="injected"):
        await persist_result_bundle(
            persistence,
            _record(),
            bundle,
            [{"run_id": "local-42"}],
        )
    assert persistence.events[-1] == ("rollback",)
    assert ("commit",) not in persistence.events


async def test_ingest_redacts_findings_artifacts_and_client_provenance() -> None:
    persistence = RecordingPersistence()
    canary = "AS_CANARY_SECRET_DO_NOT_PERSIST_123"
    bundle = ResultBundle(
        schema_version=1,
        scanners=(ScannerResult("semgrep", "completed"),),
        findings=({
            "scanner": "semgrep",
            "message": f"{canary} at /Users/alice/work/repo/app.py",
        },),
        artifacts={
            "sarif": json.dumps({"message": canary, "path": "/home/alice/repo"}).encode(),
            "findings": json.dumps({"source": "local", "secret": canary}).encode(),
        },
    )
    envelope = LocalIngestEnvelope(
        run_id="local-42",
        project=ResolvedProject(42, "owner/repo", 99),
        submitted_by_user_id=7,
        submitting_token_id="token-id",
        submitting_token_label="laptop",
        payload_hash="b" * 64,
        commit_sha="a" * 40,
        git_object_format="sha1",
        branch="main",
        working_tree_dirty=True,
        source_content_hash="c" * 64,
        source_manifest_version="assurance-snapshot-v1",
        client_provenance_version=1,
        client_provenance={"diagnostic": f"{canary} /Users/alice/work"},
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    assert await ingest_result_bundle(persistence, envelope, bundle) == "ingested"
    persisted = b"\n".join(persistence.artifacts).decode()
    assert canary not in persisted
    assert "/Users/alice" not in persisted
    assert canary not in persistence.findings[0]["message"]
    assert "/Users/alice" not in persistence.findings[0]["message"]


async def test_local_ingest_rejects_bundle_without_scanner_results() -> None:
    persistence = RecordingPersistence()
    envelope = LocalIngestEnvelope(
        run_id="local-42",
        project=ResolvedProject(42, "owner/repo"),
        submitted_by_user_id=7,
        submitting_token_id="token-id",
        submitting_token_label="laptop",
        payload_hash="b" * 64,
        commit_sha="a" * 40,
        git_object_format="sha1",
        branch=None,
        working_tree_dirty=False,
        source_content_hash="c" * 64,
        source_manifest_version="assurance-snapshot-v1",
        client_provenance_version=1,
        client_provenance={},
        started_at=None,
        completed_at=None,
    )
    with pytest.raises(ValueError, match="no scanner results"):
        await ingest_result_bundle(persistence, envelope, ResultBundle(schema_version=1))
    assert persistence.events == []
