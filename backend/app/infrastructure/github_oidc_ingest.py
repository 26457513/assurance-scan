"""SQLAlchemy composition for authenticated GitHub Actions result ingestion."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories.github_ingest_requests import (
    SqlAlchemyGithubIdempotencyRepository,
)
from app.infrastructure.db.repositories.github_ingest_usage import (
    SqlAlchemyGithubUsageQuotaRepository,
)
from app.infrastructure.db.repositories.ingest_attempts import (
    SqlAlchemyIngestAttemptRepository,
)
from app.modules.atomic.ingestion.ingest_attempt import IngestAttemptRecord
from app.modules.atomic.ingestion.idempotency_guard import GithubIdempotencyClaim
from app.modules.atomic.ingestion.result_persister._adapters import SqlAlchemyIngestPersistence
from app.modules.workflows.github_oidc_ingest import (
    GithubIngestCommand,
    GithubIngestDependencies,
    GithubIngestResult,
    ingest_github_result,
)
from app.modules.shared.contracts.ingest_v2 import (
    GITHUB_USAGE_LIMITS_V2,
    SHARED_USAGE_LIMITS_V2,
    GitHubUsageLimitsV2,
    SharedUsageLimitsV2,
)


class GithubClaimCompletingSqlAlchemyPersistence(SqlAlchemyIngestPersistence):
    """Complete a fenced GitHub claim in the result graph transaction."""

    def __init__(
        self,
        session: AsyncSession,
        claims: SqlAlchemyGithubIdempotencyRepository,
    ) -> None:
        super().__init__(session)
        self._claims = claims
        self._claim: GithubIdempotencyClaim | None = None
        self._attempt: IngestAttemptRecord | None = None

    def bind_claim(self, claim: GithubIdempotencyClaim) -> None:
        if self._claim is not None:
            raise RuntimeError("GitHub ingest persistence is already bound to a claim")
        self._claim = claim

    def bind_attempt(self, attempt: IngestAttemptRecord) -> None:
        if self._attempt is not None:
            raise RuntimeError("GitHub ingest persistence is already bound to an attempt")
        self._attempt = attempt

    async def before_commit(self, run_id: str) -> None:
        if self._claim is None:
            raise RuntimeError("GitHub ingest persistence has no idempotency claim")
        completed = await self._claims.complete(
            self._claim,
            run_id=run_id,
            now=datetime.now(timezone.utc),
        )
        if not completed:
            raise RuntimeError("GitHub ingest idempotency lease was lost before commit")
        if self._attempt is None:
            raise RuntimeError("GitHub ingest persistence has no audit attempt")
        await SqlAlchemyIngestAttemptRepository(self._session).stage(self._attempt)


class SqlAlchemyGithubOidcIngestWorkflow:
    """Application adapter composed from same-session SQL repositories."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        github_usage_limits: GitHubUsageLimitsV2 = GITHUB_USAGE_LIMITS_V2,
        shared_usage_limits: SharedUsageLimitsV2 = SHARED_USAGE_LIMITS_V2,
    ) -> None:
        claims = SqlAlchemyGithubIdempotencyRepository(session)
        self._dependencies = GithubIngestDependencies(
            claims=claims,
            quotas=SqlAlchemyGithubUsageQuotaRepository(session),
            attempts=SqlAlchemyIngestAttemptRepository(session),
            persistence=GithubClaimCompletingSqlAlchemyPersistence(session, claims),
            github_usage_limits=github_usage_limits,
            shared_usage_limits=shared_usage_limits,
        )

    async def ingest(self, command: GithubIngestCommand) -> GithubIngestResult:
        return await ingest_github_result(command, self._dependencies)


__all__ = [
    "GithubClaimCompletingSqlAlchemyPersistence",
    "SqlAlchemyGithubOidcIngestWorkflow",
]
