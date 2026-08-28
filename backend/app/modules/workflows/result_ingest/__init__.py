"""Public API for source-neutral result ingestion."""

from app.modules.shared.contracts.ingest import (
    GitHubIngestEnvelope,
    IngestStatus,
    LocalIngestEnvelope,
    ResolvedProject,
    ResultBundle,
    ScannerResult,
)

from .models import IngestPersistencePort
from .service import (
    build_github_inputs,
    build_local_result_bundle,
    github_run_id,
    ingest_result_bundle,
)

__all__ = [
    "GitHubIngestEnvelope",
    "IngestPersistencePort",
    "IngestStatus",
    "LocalIngestEnvelope",
    "ResolvedProject",
    "ResultBundle",
    "ScannerResult",
    "build_github_inputs",
    "build_local_result_bundle",
    "github_run_id",
    "ingest_result_bundle",
]
