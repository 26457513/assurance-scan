"""Focused tests for the behavior-preserving ingestion extraction."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.modules.atomic.ingestion.bundle_validator import validate_bundle
from app.modules.atomic.ingestion.finding_normalizer import normalize_findings
from app.modules.atomic.ingestion.idempotency_guard import run_exists
from app.modules.atomic.ingestion.result_persister import persist_result_bundle
from app.modules.shared.contracts.ingest import BLOB_ARTIFACTS
from app.modules.shared.contracts.ingest import ResultBundle, RunRecord
from app.modules.workflows import github_result_ingest


def test_ingestion_workflow_and_shared_blob_contract_are_public() -> None:
    assert github_result_ingest.ci_run_id({"github_run_id": 42}) == "gh-42"
    assert BLOB_ARTIFACTS == (
        ("sarif", "sarif", "assurance-scan/sarif"),
        ("sbom", "cyclonedx-json", "assurance-scan/sbom"),
        ("findings", "json", "assurance-scan/findings"),
    )


def test_bundle_validator_preserves_legacy_permissive_inputs() -> None:
    payload = {"github_run_id": 42}
    metadata = {"repo": "owner/repo"}
    blobs = {"sarif": b"{}"}

    bundle = validate_bundle(payload, metadata, blobs)

    assert bundle.payload is payload
    assert bundle.metadata is metadata
    assert bundle.blobs is blobs
    assert validate_bundle(None, metadata).blobs == {}


def test_finding_normalizer_preserves_defaults_and_fields() -> None:
    rows = normalize_findings(
        "gh-42",
        [
            {
                "scanner": "semgrep",
                "severity": "HIGH",
                "message": None,
                "compliance_tags": None,
            },
            {
                "scanner": "gitleaks",
                "rule_id": "secret",
                "severity": "CRITICAL",
                "file_path": "config.py",
                "line_start": 2,
                "line_end": 3,
                "message": "credential",
                "theme": "secrets",
                "fix_strategy": "rotate",
                "compliance_tags": ["SOC2"],
            },
        ],
    )

    assert rows == [
        {
            "run_id": "gh-42",
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
        },
        {
            "run_id": "gh-42",
            "scanner_kind": "gitleaks",
            "rule_id": "secret",
            "severity": "CRITICAL",
            "file_path": "config.py",
            "line_start": 2,
            "line_end": 3,
            "message": "credential",
            "theme": "secrets",
            "fix_strategy": "rotate",
            "compliance_tags": ["SOC2"],
        },
    ]


async def test_idempotency_guard_uses_repository_lookup() -> None:
    class Lookup:
        def __init__(self, value: object | None) -> None:
            self.value = value
            self.requested: list[str] = []

        async def get(self, run_id: str) -> object | None:
            self.requested.append(run_id)
            return self.value

    missing = Lookup(None)
    existing = Lookup(object())

    assert await run_exists(missing, "gh-1") is False
    assert missing.requested == ["gh-1"]
    assert await run_exists(existing, "gh-2") is True
    assert existing.requested == ["gh-2"]


async def test_result_persister_uses_only_its_explicit_port() -> None:
    class Persistence:
        def __init__(self) -> None:
            self.events: list[tuple] = []

        async def add_run(self, record: RunRecord) -> None:
            self.events.append(("run", record.run_id))

        async def add_scan_job(self, record: RunRecord) -> None:
            self.events.append(("job", record.run_id))

        async def create_scanner_run(self, run_id: str, scanner_kind: str) -> int:
            self.events.append(("scanner", run_id, scanner_kind))
            return len(self.events)

        async def mark_scanner_completed(self, scanner_run_id: int) -> None:
            self.events.append(("completed", scanner_run_id))

        async def mark_scanner_failed(self, scanner_run_id: int, error: str) -> None:
            self.events.append(("failed", scanner_run_id, error))

        async def store_artifact(
            self, scanner_run_id: int, artifact_kind: str, content: bytes
        ) -> None:
            self.events.append(("artifact", scanner_run_id, artifact_kind, content))

        async def insert_findings(self, findings: Sequence[dict[str, Any]]) -> None:
            self.events.append(("findings", len(findings)))

        async def commit(self) -> None:
            self.events.append(("commit",))

    persistence = Persistence()
    record = RunRecord(
        run_id="gh-42",
        project_path="github:owner/repo",
        options_json="{}",
        status="completed",
        started_at=None,
        completed_at=None,
        commit_sha=None,
        git_branch="main",
        error_message=None,
        findings_json="{}",
    )
    bundle = ResultBundle(
        payload={"scanner_status": {"semgrep": "ok"}},
        metadata={},
        blobs={"sarif": b"{}"},
    )

    await persist_result_bundle(persistence, record, bundle, [{"run_id": "gh-42"}])

    assert persistence.events[0:2] == [("run", "gh-42"), ("job", "gh-42")]
    assert ("findings", 1) in persistence.events
    assert persistence.events[-1] == ("commit",)
