"""SQLAlchemy composition for the local-scan ingest workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.local_ingest import (
    LocalScanIngestCommand,
    LocalScanIngestOutcome,
    LocalScanIngestResult,
    LocalScanWorkflowError,
)
from app.infrastructure.db.models import IngestRequest, Project, User
from app.infrastructure.project_access import ProjectAccessPrincipal, require_project
from app.infrastructure.db.repositories.ingest_requests import SqlAlchemyIdempotencyRepository
from app.infrastructure.db.repositories.ingest_usage import SqlAlchemyUsageQuotaRepository
from app.modules.atomic.ingestion.idempotency_guard import IdempotencyClaim
from app.modules.atomic.ingestion.result_persister._adapters import SqlAlchemyIngestPersistence
from app.modules.atomic.provenance.repository_identity import normalize_github_repository_key
from app.modules.shared.contracts.ingest import ResolvedProject
from app.modules.shared.contracts.local_scan import USAGE_LIMITS, UsageLimits
from app.modules.workflows.local_scan_ingest import (
    LocalScanCommand,
    LocalScanDependencies,
    LocalScanIngestError,
    ProjectResolution,
    ingest_local_scan,
)


class SqlAlchemyLocalProjectResolver:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, repository: str, user_id: int) -> ProjectResolution:
        key = normalize_github_repository_key(repository)
        project = (
            await self._session.execute(select(Project).where(Project.github_repo_key == key))
        ).scalar_one_or_none()
        if project is None:
            await self._session.rollback()
            return ProjectResolution(None)
        if project.hidden or project.github_repo is None:
            await self._session.rollback()
            return ProjectResolution(None, hidden=True)
        user = await self._session.get(User, user_id)
        if user is None or user.disabled_at is not None:
            await self._session.rollback()
            return ProjectResolution(None, hidden=True)
        allowed_project = await require_project(
            self._session,
            ProjectAccessPrincipal(user_id=user.id, role=user.role),
            project.id,
            "upload",
        )
        if allowed_project is None:
            await self._session.rollback()
            return ProjectResolution(None, hidden=True)
        resolved = ProjectResolution(
            ResolvedProject(
                project_id=project.id,
                repository=project.github_repo,
                github_repository_id=project.github_repository_id,
            ),
            can_upload=True,
        )
        # Quota enforcement starts a serialized write transaction. End the
        # resolver's implicit read transaction before acquiring that lock.
        await self._session.rollback()
        return resolved


@dataclass(frozen=True)
class LocalRequestStatus:
    state: str
    run_id: str | None
    project_id: int
    repository: str
    lease_expires_at: datetime | None


async def get_local_request_status(
    session: AsyncSession,
    *,
    user_id: int,
    request_id: str,
) -> LocalRequestStatus | None:
    """Resolve a claim only through its owner and visible registered project."""
    row = (
        await session.execute(
            select(IngestRequest, Project)
            .join(Project, Project.id == IngestRequest.project_id)
            .where(
                IngestRequest.submitted_by_user_id == user_id,
                IngestRequest.client_request_id == request_id,
                Project.hidden.is_(False),
            )
        )
    ).first()
    if row is None:
        return None
    claim, project = row
    if project.github_repo is None:
        return None
    user = await session.get(User, user_id)
    if user is None or user.disabled_at is not None:
        return None
    if await require_project(
        session,
        ProjectAccessPrincipal(user_id=user.id, role=user.role),
        project.id,
    ) is None:
        return None
    return LocalRequestStatus(
        state=claim.state,
        run_id=claim.run_id,
        project_id=project.id,
        repository=project.github_repo,
        lease_expires_at=claim.lease_expires_at,
    )


class ClaimCompletingSqlAlchemyPersistence(SqlAlchemyIngestPersistence):
    """Fence claim completion inside the result graph's transaction."""

    def __init__(
        self,
        session: AsyncSession,
        claims: SqlAlchemyIdempotencyRepository,
    ) -> None:
        super().__init__(session)
        self._claims = claims
        self._claim: IdempotencyClaim | None = None

    def bind_claim(self, claim: IdempotencyClaim) -> None:
        if self._claim is not None:
            raise RuntimeError("local ingest persistence is already bound to a claim")
        self._claim = claim

    async def before_commit(self, run_id: str) -> None:
        if self._claim is None:
            raise RuntimeError("local ingest persistence has no idempotency claim")
        completed = await self._claims.complete(
            self._claim,
            run_id=run_id,
            now=datetime.now(timezone.utc),
        )
        if not completed:
            raise RuntimeError("local ingest idempotency lease was lost before commit")


class SqlAlchemyLocalScanWorkflow:
    """HTTP-port implementation composed from same-session SQL adapters."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        public_base_url: str,
        usage_limits: UsageLimits | None = None,
    ) -> None:
        claims = SqlAlchemyIdempotencyRepository(session)
        self._dependencies = LocalScanDependencies(
            projects=SqlAlchemyLocalProjectResolver(session),
            quotas=SqlAlchemyUsageQuotaRepository(session),
            claims=claims,
            persistence=ClaimCompletingSqlAlchemyPersistence(session, claims),
            usage_limits=usage_limits or USAGE_LIMITS,
        )
        self._public_base_url = public_base_url

    async def ingest_local_scan(
        self,
        command: LocalScanIngestCommand,
    ) -> LocalScanIngestResult:
        try:
            result = await ingest_local_scan(
                LocalScanCommand(
                    user_id=command.principal.user_id,
                    token_id=command.principal.token_id,
                    token_label=command.principal.token_label,
                    token_scopes=frozenset(command.principal.scope.split()),
                    request_id=command.idempotency_key,
                    metadata=command.metadata,
                    findings=command.findings,
                    accepted_bytes=command.accepted_bytes,
                    findings_bytes=command.findings_bytes,
                    sarif_bytes=command.sarif_bytes,
                    sbom_bytes=command.sbom_bytes,
                    payload_hash=command.payload_hash,
                    public_base_url=self._public_base_url,
                ),
                self._dependencies,
            )
        except LocalScanIngestError as exc:
            raise LocalScanWorkflowError(
                status=exc.status,
                code=exc.code,
                title=exc.title,
                detail=exc.detail,
                retryable=exc.retryable,
                retry_after_seconds=exc.retry_after_seconds,
            ) from exc
        return LocalScanIngestResult(
            outcome=LocalScanIngestOutcome(result.outcome.value),
            run_id=result.run_id,
            project_id=result.project_id,
            repository=result.repository,
            run_url=result.run_url,
            status=result.status,
            status_url=result.status_url,
            retry_after_seconds=result.retry_after_seconds,
        )


__all__ = [
    "ClaimCompletingSqlAlchemyPersistence",
    "LocalRequestStatus",
    "SqlAlchemyLocalProjectResolver",
    "SqlAlchemyLocalScanWorkflow",
    "get_local_request_status",
]
