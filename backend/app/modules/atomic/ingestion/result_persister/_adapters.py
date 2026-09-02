"""Private SQLAlchemy adapter for result-ingestion persistence ports."""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Project, Run, ScanJob, ScannerRun
from app.infrastructure.db.repositories.findings import FindingRepository
from app.infrastructure.db.repositories.runs import RunRepository
from app.infrastructure.db.repositories.scanner_artifacts import ScannerArtifactRepository
from app.infrastructure.db.repositories.scanner_runs import ScannerRunRepository
from app.infrastructure.db.repositories.source_contexts import SourceContextRepository
from app.modules.shared.contracts.findings import NormalizedFinding
from app.modules.shared.contracts.ingest import RunRecord, ScannerResult
from app.modules.shared.contracts.source_context import SourceContextPayload


class SqlAlchemyIngestPersistence:
    """Adapt existing SQLAlchemy repositories to the ingestion ports."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._runs = RunRepository(session)
        self._scanner_runs = ScannerRunRepository(session)
        self._artifacts = ScannerArtifactRepository(session)
        self._findings = FindingRepository(session)
        self._source_contexts = SourceContextRepository(session)

    async def get(self, run_id: str) -> object | None:
        return await self._runs.get(run_id)

    async def add_run(self, record: RunRecord) -> None:
        local_run_number: int | None = None
        if record.origin == "local":
            local_run_number = (
                await self._session.execute(
                    update(Project)
                    .where(Project.id == record.project_id)
                    .values(local_run_counter=Project.local_run_counter + 1)
                    .returning(Project.local_run_counter)
                )
            ).scalar_one()
        self._session.add(Run(
            run_id=record.run_id,
            project_id=record.project_id,
            origin=record.origin,
            options_json=record.options_json,
            status=record.status,
            started_at=record.started_at,
            completed_at=record.completed_at,
            commit_sha=record.commit_sha,
            git_branch=record.git_branch,
            git_object_format=record.git_object_format,
            repository_full_name_at_scan=record.repository_full_name_at_scan,
            working_tree_dirty=record.working_tree_dirty,
            source_content_hash=record.source_content_hash,
            source_manifest_version=record.source_manifest_version,
            submitted_by_user_id=record.submitted_by_user_id,
            submitting_token_id=record.submitting_token_id,
            payload_hash=record.payload_hash,
            client_provenance_version=record.client_provenance_version,
            client_provenance_json=record.client_provenance_json,
            github_run_id=record.github_run_id,
            github_run_number=record.github_run_number,
            github_run_attempt=record.github_run_attempt,
            github_run_url=record.github_run_url,
            github_event=record.github_event,
            github_actor=record.github_actor,
            github_head_sha=record.github_head_sha,
            local_run_number=local_run_number,
            local_machine_label=record.local_machine_label,
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

    async def create_scanner_run(self, run_id: str, result: ScannerResult) -> int:
        scanner_run = await self._scanner_runs.create(
            run_id,
            result.kind,
            image_reference=result.image_reference,
            image_digest=result.image_digest,
            tool_version=result.tool_version,
            database_version_json=(
                None
                if result.database_version is None
                else '{"version": ' + json.dumps(result.database_version) + "}"
            ),
        )
        return scanner_run.id

    async def mark_scanner_completed(self, scanner_run_id: int) -> None:
        await self._scanner_runs.mark_completed(scanner_run_id)

    async def mark_scanner_failed(self, scanner_run_id: int, error: str) -> None:
        await self._scanner_runs.mark_failed(scanner_run_id, error)

    async def mark_scanner_skipped(
        self,
        scanner_run_id: int,
        reason: str | None,
    ) -> None:
        await self._session.execute(
            update(ScannerRun)
            .where(ScannerRun.id == scanner_run_id)
            .values(status="skipped", error_message=reason)
        )

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

    async def insert_source_contexts(
        self,
        run_id: str,
        contexts: Sequence[SourceContextPayload],
    ) -> None:
        await self._source_contexts.bulk_insert(run_id, contexts)

    async def commit(self) -> None:
        await self._session.commit()

    async def before_commit(self, run_id: str) -> None:
        """Default hook for ingests without an external idempotency claim."""

    async def rollback(self) -> None:
        await self._session.rollback()


__all__ = ["SqlAlchemyIngestPersistence"]
