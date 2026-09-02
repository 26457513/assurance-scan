"""Public API for authenticated GitHub Actions result ingestion."""

from .models import (
    GithubClaimCompletingPersistencePort,
    GithubIngestCommand,
    GithubIngestDependencies,
    GithubIngestError,
    GithubIngestOutcome,
    GithubIngestResult,
)
from .service import ingest_github_result

__all__ = [
    "GithubClaimCompletingPersistencePort",
    "GithubIngestCommand",
    "GithubIngestDependencies",
    "GithubIngestError",
    "GithubIngestOutcome",
    "GithubIngestResult",
    "ingest_github_result",
]
