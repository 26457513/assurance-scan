"""Private SQLAlchemy adapter for result-ingestion persistence ports."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Project, Run, ScanJob
from app.infrastructure.db.repositories.findings import FindingRepository
from app.infrastructure.db.repositories.runs import RunRepository
from app.infrastructure.db.repositories.scanner_artifacts import ScannerArtifactRepository
from app.infrastructure.db.repositories.scanner_runs import ScannerRunRepository
from app.modules.shared.contracts.findings import NormalizedFinding
from app.modules.shared.contracts.ingest import ResolvedGitHubProject, RunRecord
from app.modules.atomic.provenance.repository_identity import normalize_github_repository_key


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

    async def resolve_github_project(self, repository: str) -> ResolvedGitHubProject | None:
        key = normalize_github_repository_key(repository)
        project = (
            await self._session.execute(
                select(Project).where(
                    Project.github_repo_key == key,
                    Project.hidden.is_(False),
                )
            )
        ).scalars().first()
        if project is None or project.github_repo is None:
            return None
        return ResolvedGitHubProject(project_id=project.id, repository=project.github_repo)

    async def add_run(self, record: RunRecord) -> None:
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
