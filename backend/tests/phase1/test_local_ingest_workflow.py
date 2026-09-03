"""End-to-end WS2 local ingestion through the real SQL composition."""

from __future__ import annotations

import json
import logging
import uuid
from unittest.mock import AsyncMock
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select, text, update

from app.api.schemas.local_ingest import LocalScanIngestCommand, LocalScanIngestOutcome
from app.api.schemas.local_ingest import LocalScanWorkflowError
from app.infrastructure.db.models import (
    ApiToken,
    Finding,
    IngestRequest,
    IngestAttempt,
    IngestUsageCharge,
    Project,
    ProjectMembership,
    Run,
    ScannerArtifact,
    ScannerRun,
    User,
)
from app.infrastructure.local_scan_ingest import SqlAlchemyLocalScanWorkflow
from app.infrastructure.local_scan_ingest import ClaimCompletingSqlAlchemyPersistence
from app.infrastructure.project_access import SYSTEM_PRINCIPAL
from app.infrastructure.db.retention import run_retention_cleanup
from app.infrastructure.db.repositories.ingest_requests import SqlAlchemyIdempotencyRepository
from app.infrastructure.db.repositories.ingest_usage import SqlAlchemyUsageQuotaRepository
from app.api.routes.scans import delete_scan
from app.modules.atomic.access.scan_token import ScanTokenPrincipal
from app.modules.atomic.ingestion.idempotency_guard import ClaimCommand, acquire_claim
from app.modules.atomic.ingestion.usage_quota import QuotaCommand
from app.modules.shared.contracts.local_scan import USAGE_LIMITS, UsageLimits
from app.modules.shared.contracts.ingest_v2 import SHARED_USAGE_LIMITS_V2, SharedUsageLimitsV2


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "local-scan" / "valid"
REQUEST_ID = "018f47a2-4c72-4c9e-9f60-780cb70b8fe4"
TOKEN_ID = "a8e311e0-a983-4bb9-ab55-adc10a6bb715"


class _FailingPersistence(ClaimCompletingSqlAlchemyPersistence):
    async def insert_findings(self, findings: object) -> None:
        raise RuntimeError("injected local persistence failure")


async def _seed_identity(session) -> None:
    now = datetime.now(timezone.utc)
    session.add_all(
        [
            User(id=7, email="alice@example.test", role="user", created_at=now),
            Project(
                id=42,
                tag="assurance-scan",
                github_repo="26457513/assurance-scan",
                github_repo_key="26457513/assurance-scan",
                github_repository_id=123456,
                created_at=now,
            ),
        ]
    )
    await session.commit()
    session.add(
        ProjectMembership(
            user_id=7,
            project_id=42,
            permission="upload",
            source="github_app",
            verified_at=now,
            expires_at=now + timedelta(minutes=5),
        )
    )
    session.add(
        ApiToken(
            id=TOKEN_ID,
            user_id=7,
            label="laptop",
            label_key="laptop",
            selector="abcdefghijklmnop",
            secret_digest=b"x" * 32,
            scope="scans:upload",
            token_version=1,
            expires_at=now + timedelta(days=30),
            created_at=now,
        )
    )
    await session.commit()


def _command() -> LocalScanIngestCommand:
    metadata_bytes = (FIXTURES / "metadata.json").read_bytes()
    findings_bytes = (FIXTURES / "findings.json").read_bytes()
    return LocalScanIngestCommand(
        principal=ScanTokenPrincipal(
            token_id=TOKEN_ID,
            user_id=7,
            account_name="alice@example.test",
            token_label="laptop",
            scope="scans:upload",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ),
        correlation_id=str(uuid.uuid4()),
        idempotency_key=REQUEST_ID,
        metadata=json.loads(metadata_bytes),
        findings=json.loads(findings_bytes),
        accepted_bytes=len(metadata_bytes) + len(findings_bytes) + 512,
        findings_bytes=findings_bytes,
        payload_hash="d" * 64,
    )


async def test_real_local_workflow_persists_one_graph_and_replays_without_duplicates(
    session,
) -> None:
    await _seed_identity(session)

    created = await SqlAlchemyLocalScanWorkflow(session, public_base_url="https://scan.example.test").ingest_local_scan(
        _command()
    )
    replayed = await SqlAlchemyLocalScanWorkflow(
        session, public_base_url="https://scan.example.test"
    ).ingest_local_scan(_command())

    assert created.outcome is LocalScanIngestOutcome.CREATED
    assert created.run_id is not None and created.run_id.startswith("local-")
    assert created.run_url == f"https://scan.example.test/scans/{created.run_id}"
    assert replayed.outcome is LocalScanIngestOutcome.REPLAYED
    assert replayed.run_id == created.run_id
    assert await session.scalar(select(func.count()).select_from(Run)) == 1
    assert await session.scalar(select(func.count()).select_from(Finding)) == 1
    assert await session.scalar(select(func.count()).select_from(ScannerArtifact)) == 1
    assert await session.scalar(select(func.count()).select_from(ScannerRun)) == 2

    run = (await session.execute(select(Run))).scalar_one()
    claim = (await session.execute(select(IngestRequest))).scalar_one()
    assert run.project_id == 42
    assert run.origin == "local"
    assert run.git_branch == "feature/local-scan"
    assert run.working_tree_dirty is True
    assert run.submitted_by_user_id == 7
    assert run.submitting_token_id == TOKEN_ID
    assert run.local_run_number == 1
    assert run.local_machine_label == "laptop"
    assert claim.state == "completed"
    assert claim.run_id == run.run_id
    assert claim.lease_id is None
    attempts = (await session.execute(select(IngestAttempt))).scalars().all()
    assert [attempt.outcome for attempt in attempts] == ["accepted", "replayed"]
    assert [attempt.reason_code for attempt in attempts] == ["accepted", "idempotent_replay"]
    assert [attempt.retryable for attempt in attempts] == [False, False]
    assert all(attempt.origin == "local" for attempt in attempts)
    assert all(attempt.run_id == run.run_id for attempt in attempts)
    assert all(attempt.submitted_by_user_id == 7 for attempt in attempts)
    assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 1


async def test_local_workflow_failure_rolls_back_graph_records_evidence_and_retries(
    session,
) -> None:
    await _seed_identity(session)
    command = _command()
    workflow = SqlAlchemyLocalScanWorkflow(session, public_base_url="https://scan.example.test")
    claims = workflow._dependencies.claims
    workflow._dependencies = replace(
        workflow._dependencies,
        persistence=_FailingPersistence(session, claims),
    )

    with pytest.raises(RuntimeError, match="injected local persistence failure"):
        await workflow.ingest_local_scan(command)

    assert await session.scalar(select(func.count()).select_from(Run)) == 0
    claim = (await session.execute(select(IngestRequest))).scalar_one()
    assert claim.state == "failed"
    attempts = (await session.execute(select(IngestAttempt))).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].outcome == "failed_internal"
    assert attempts[0].reason_code == "internal_persistence_failed"
    assert attempts[0].retryable is True
    assert attempts[0].correlation_id == command.correlation_id
    assert attempts[0].run_id is None
    assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 1
    await session.rollback()

    retry = await SqlAlchemyLocalScanWorkflow(
        session,
        public_base_url="https://scan.example.test",
    ).ingest_local_scan(replace(command, correlation_id=str(uuid.uuid4())))
    assert retry.outcome is LocalScanIngestOutcome.CREATED
    assert await session.scalar(select(func.count()).select_from(Run)) == 1
    assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 2


async def test_local_cleanup_failures_do_not_mask_primary_failure(
    session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _seed_identity(session)
    command = _command()
    workflow = SqlAlchemyLocalScanWorkflow(session, public_base_url="https://scan.example.test")
    claims = workflow._dependencies.claims
    workflow._dependencies = replace(
        workflow._dependencies,
        persistence=_FailingPersistence(session, claims),
    )
    fail_claim = AsyncMock(side_effect=RuntimeError("claim cleanup secret"))
    fail_attempt = AsyncMock(side_effect=RuntimeError("attempt cleanup secret"))
    monkeypatch.setattr(workflow._dependencies.claims, "fail", fail_claim)
    monkeypatch.setattr(workflow._dependencies.attempts, "record", fail_attempt)
    caplog.set_level(logging.ERROR, logger="app.modules.workflows.local_scan_ingest.service")

    with pytest.raises(RuntimeError, match="injected local persistence failure"):
        await workflow.ingest_local_scan(command)

    fail_claim.assert_awaited_once()
    fail_attempt.assert_awaited_once()
    assert command.correlation_id in caplog.text
    assert "claim cleanup secret" not in caplog.text
    assert "attempt cleanup secret" not in caplog.text


@pytest.mark.parametrize(
    ("limits", "shared_limits", "status", "reason_code", "retryable"),
    [
        (replace(USAGE_LIMITS, uploads_per_token_hour=0), SharedUsageLimitsV2(), 429, "quota_exceeded", True),
        (replace(USAGE_LIMITS, inflight_per_token=0), SharedUsageLimitsV2(), 429, "capacity_exceeded", True),
        (replace(USAGE_LIMITS, retained_bytes_per_user=0), SharedUsageLimitsV2(), 507, "storage_quota_exceeded", False),
    ],
)
async def test_local_workflow_quota_rejections_create_safe_attempt_only(
    session,
    limits: UsageLimits,
    shared_limits: SharedUsageLimitsV2,
    status: int,
    reason_code: str,
    retryable: bool,
) -> None:
    await _seed_identity(session)
    command = _command()
    workflow = SqlAlchemyLocalScanWorkflow(
        session,
        public_base_url="https://scan.example.test",
        usage_limits=limits,
        shared_usage_limits=shared_limits,
    )

    with pytest.raises(LocalScanWorkflowError) as raised:
        await workflow.ingest_local_scan(command)

    assert raised.value.status == status
    attempt = (await session.execute(select(IngestAttempt))).scalar_one()
    assert attempt.origin == "local"
    assert attempt.outcome == "rejected"
    assert attempt.reason_code == reason_code
    assert attempt.retryable is retryable
    assert attempt.correlation_id == command.correlation_id
    assert attempt.run_id is None
    assert await session.scalar(select(func.count()).select_from(IngestRequest)) == 0
    assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 0


async def test_local_active_duplicate_is_replayed_without_second_charge(session) -> None:
    await _seed_identity(session)
    command = _command()
    now = datetime.now(timezone.utc)
    reservation = await SqlAlchemyUsageQuotaRepository(session).reserve(
        QuotaCommand(
            user_id=7,
            token_id=TOKEN_ID,
            client_request_id=REQUEST_ID,
            accepted_bytes=command.accepted_bytes,
            project_id=42,
            payload_hash=command.payload_hash,
            correlation_id=command.correlation_id,
        ),
        limits=USAGE_LIMITS,
        shared_limits=SHARED_USAGE_LIMITS_V2,
        now=now,
    )
    assert reservation.allowed
    claim = await acquire_claim(
        ClaimCommand(
            user_id=7,
            token_id=TOKEN_ID,
            client_request_id=REQUEST_ID,
            project_id=42,
            payload_hash=command.payload_hash,
            accepted_bytes=command.accepted_bytes,
        ),
        repository=SqlAlchemyIdempotencyRepository(session),
        now=now,
    )
    assert claim.acquired

    result = await SqlAlchemyLocalScanWorkflow(
        session,
        public_base_url="https://scan.example.test",
    ).ingest_local_scan(replace(command, correlation_id=str(uuid.uuid4())))

    assert result.outcome is LocalScanIngestOutcome.IN_PROGRESS
    assert result.run_id is None
    assert result.status_url is not None
    assert result.retry_after_seconds is not None
    attempt = (await session.execute(select(IngestAttempt))).scalar_one()
    assert attempt.outcome == "replayed"
    assert attempt.reason_code == "idempotent_replay"
    assert attempt.retryable is True
    assert attempt.run_id is None
    assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 1


async def test_local_conflict_and_tombstone_rejections_do_not_recharge(session) -> None:
    await session.execute(text("PRAGMA foreign_keys=ON"))
    await _seed_identity(session)
    command = _command()

    def workflow() -> SqlAlchemyLocalScanWorkflow:
        return SqlAlchemyLocalScanWorkflow(session, public_base_url="https://scan.example.test")

    created = await workflow().ingest_local_scan(command)

    conflict_command = replace(command, payload_hash="e" * 64, correlation_id=str(uuid.uuid4()))
    with pytest.raises(LocalScanWorkflowError) as conflict:
        await workflow().ingest_local_scan(conflict_command)
    assert conflict.value.status == 409
    assert conflict.value.code == "idempotency_conflict"
    await session.rollback()

    await delete_scan(created.run_id or "", SYSTEM_PRINCIPAL, session)
    tombstone_command = replace(command, correlation_id=str(uuid.uuid4()))
    with pytest.raises(LocalScanWorkflowError) as tombstone:
        await workflow().ingest_local_scan(tombstone_command)
    assert tombstone.value.status == 410
    assert tombstone.value.code == "idempotency_tombstoned"

    attempts = (await session.execute(select(IngestAttempt))).scalars().all()
    assert [attempt.outcome for attempt in attempts] == ["accepted", "rejected", "rejected"]
    assert [attempt.reason_code for attempt in attempts] == [
        "accepted",
        "idempotency_conflict",
        "idempotency_conflict",
    ]
    assert attempts[1].correlation_id == conflict_command.correlation_id
    assert attempts[2].correlation_id == tombstone_command.correlation_id
    assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 1


async def test_local_run_numbers_advance_per_project_and_replay_is_stable(session) -> None:
    await _seed_identity(session)

    def workflow() -> SqlAlchemyLocalScanWorkflow:
        return SqlAlchemyLocalScanWorkflow(session, public_base_url="https://scan.example.test")

    first = await workflow().ingest_local_scan(_command())
    second = await workflow().ingest_local_scan(
        replace(
            _command(),
            idempotency_key="128f47a2-4c72-4c9e-9f60-780cb70b8fe4",
            payload_hash="e" * 64,
        )
    )
    replayed = await workflow().ingest_local_scan(_command())

    rows = (await session.execute(select(Run).order_by(Run.local_run_number))).scalars().all()
    project = await session.get(Project, 42)
    assert first.outcome is LocalScanIngestOutcome.CREATED
    assert second.outcome is LocalScanIngestOutcome.CREATED
    assert replayed.outcome is LocalScanIngestOutcome.REPLAYED
    assert [row.local_run_number for row in rows] == [1, 2]
    assert [row.local_machine_label for row in rows] == ["laptop", "laptop"]
    assert project is not None and project.local_run_counter == 2


async def test_project_override_selects_registered_upstream_and_is_audited(session) -> None:
    await _seed_identity(session)
    command = _command()
    metadata = dict(command.metadata)
    metadata["repository"] = "alice/assurance-scan"
    metadata["project_override"] = "26457513/assurance-scan"
    command = LocalScanIngestCommand(
        principal=command.principal,
        correlation_id=command.correlation_id,
        idempotency_key=command.idempotency_key,
        metadata=metadata,
        findings=command.findings,
        accepted_bytes=command.accepted_bytes,
        findings_bytes=command.findings_bytes,
        payload_hash=command.payload_hash,
    )

    result = await SqlAlchemyLocalScanWorkflow(session, public_base_url="https://scan.example.test").ingest_local_scan(
        command
    )

    run = (await session.execute(select(Run))).scalar_one()
    provenance = json.loads(run.client_provenance_json or "{}")
    assert result.repository == "26457513/assurance-scan"
    assert provenance["detected_repository"] == "alice/assurance-scan"
    assert provenance["project_override"] == "26457513/assurance-scan"


async def test_retention_removes_raw_data_then_tombstones_expired_run(session) -> None:
    await session.execute(text("PRAGMA foreign_keys=ON"))
    await _seed_identity(session)
    created = await SqlAlchemyLocalScanWorkflow(session, public_base_url="https://scan.example.test").ingest_local_scan(
        _command()
    )
    now = datetime.now(timezone.utc)
    await session.execute(update(ScannerArtifact).values(created_at=now - timedelta(days=31)))
    await session.commit()

    raw_cleanup = await run_retention_cleanup(session, now=now)

    assert raw_cleanup.raw_artifacts == 1
    assert raw_cleanup.runs == 0
    assert await session.scalar(select(func.count()).select_from(Run)) == 1
    await session.execute(
        update(Run)
        .where(Run.run_id == created.run_id)
        .values(
            started_at=now - timedelta(days=366),
            completed_at=now - timedelta(days=366),
        )
    )
    await session.commit()

    run_cleanup = await run_retention_cleanup(session, now=now)

    assert run_cleanup.runs == 1
    assert await session.scalar(select(func.count()).select_from(Run)) == 0
    claim = (await session.execute(select(IngestRequest))).scalar_one()
    assert claim.state == "tombstoned"
    assert claim.run_id is None

    tombstone_cleanup = await run_retention_cleanup(
        session,
        now=now + timedelta(days=31),
    )
    assert tombstone_cleanup.tombstones == 1
    assert tombstone_cleanup.ingest_attempts == 1
    assert await session.scalar(select(func.count()).select_from(IngestRequest)) == 0


async def test_retention_cleanup_bounds_each_table_batch(
    session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.infrastructure.db.retention as retention

    await session.execute(text("PRAGMA foreign_keys=ON"))
    await _seed_identity(session)
    await SqlAlchemyLocalScanWorkflow(session, public_base_url="https://scan.example.test").ingest_local_scan(
        _command()
    )
    await SqlAlchemyLocalScanWorkflow(session, public_base_url="https://scan.example.test").ingest_local_scan(
        replace(
            _command(),
            idempotency_key="128f47a2-4c72-4c9e-9f60-780cb70b8fe4",
            payload_hash="e" * 64,
            correlation_id=str(uuid.uuid4()),
        )
    )
    now = datetime.now(timezone.utc)
    cleanup_at = now + timedelta(days=31)
    expired = now - timedelta(days=400)
    await session.execute(update(Run).values(started_at=expired, completed_at=expired))
    await session.execute(update(ScannerArtifact).values(created_at=expired))
    await session.commit()
    monkeypatch.setattr(retention, "RETENTION_BATCH_SIZE", 1)

    first = await run_retention_cleanup(session, now=cleanup_at)
    assert first.raw_artifacts == 1
    assert first.runs == 1
    assert first.ingest_attempts == 1
    assert first.usage_charges == 1
    assert await session.scalar(select(func.count()).select_from(Run)) == 1
    assert await session.scalar(select(func.count()).select_from(IngestAttempt)) == 1
    assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 1
    await session.rollback()

    second = await run_retention_cleanup(session, now=cleanup_at)
    assert second.raw_artifacts == 1
    assert second.runs == 1
    assert second.ingest_attempts == 1
    assert second.usage_charges == 1
    assert await session.scalar(select(func.count()).select_from(Run)) == 0
    assert await session.scalar(select(func.count()).select_from(IngestAttempt)) == 0
    assert await session.scalar(select(func.count()).select_from(IngestUsageCharge)) == 0


async def test_explicit_scan_deletion_preserves_idempotency_tombstone(session) -> None:
    await session.execute(text("PRAGMA foreign_keys=ON"))
    await _seed_identity(session)
    created = await SqlAlchemyLocalScanWorkflow(session, public_base_url="https://scan.example.test").ingest_local_scan(
        _command()
    )

    response = await delete_scan(created.run_id or "", SYSTEM_PRINCIPAL, session)

    assert response == {"status": "deleted", "run_id": created.run_id}
    claim = (await session.execute(select(IngestRequest))).scalar_one()
    assert claim.state == "tombstoned"
    assert claim.run_id is None
