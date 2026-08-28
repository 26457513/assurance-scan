"""Private SQLAlchemy adapter for result-ingestion persistence ports."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Run, ScanJob
from app.infrastructure.db.repositories.findings import FindingRepository
from app.infrastructure.db.repositories.runs import RunRepository
from app.infrastructure.db.repositories.scanner_artifacts import ScannerArtifactRepository
from app.infrastructure.db.repositories.scanner_runs import ScannerRunRepository
from app.modules.shared.contracts.findings import NormalizedFinding
from app.modules.shared.contracts.ingest import RunRecord


class SqlAlchemyIngestPersistence:
    """Adapt existing SQLAlchemy repositories to the ingestion ports."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._runs = RunRepository(session)
        self._scanner_runs = ScannerRunRepository(session)
        self._artifacts = ScannerArtifactRepository(session)
        self._findings = FindingRepository(session)

    async def get(self, run_id: str) -> object | None:
        return await self._runs.get(run_id)

    async def add_run(self, record: RunRecord) -> None:
        self._session.add(Run(
            run_id=record.run_id,
            project_path=record.project_path,
            options_json=record.options_json,
            status=record.status,
            started_at=record.started_at,
            completed_at=record.completed_at,
            commit_sha=record.commit_sha,
            git_branch=record.git_branch,
            error_message=record.error_message,
            findings_json=record.findings_json,
        ))

    async def add_scan_job(self, record: RunRecord) -> None:
        self._session.add(ScanJob(
            run_id=record.run_id,
            state=record.status,
            queued_at=record.started_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
            error_message=record.error_message,
        ))

    async def create_scanner_run(self, run_id: str, scanner_kind: str) -> int:
        scanner_run = await self._scanner_runs.create(run_id, scanner_kind)
        return scanner_run.id

    async def mark_scanner_completed(self, scanner_run_id: int) -> None:
        await self._scanner_runs.mark_completed(scanner_run_id)

    async def mark_scanner_failed(self, scanner_run_id: int, error: str) -> None:
        await self._scanner_runs.mark_failed(scanner_run_id, error)

    async def store_artifact(
        self,
        scanner_run_id: int,
        artifact_kind: str,
        content: bytes,
    ) -> None:
        await self._artifacts.store(
            scanner_run_id=scanner_run_id,
            kind=artifact_kind,
            content=content,
        )

    async def insert_findings(
        self,
        findings: Sequence[NormalizedFinding],
    ) -> None:
        await self._findings.bulk_insert(findings)

    async def commit(self) -> None:
        await self._session.commit()


__all__ = ["SqlAlchemyIngestPersistence"]
