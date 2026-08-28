"""Public API for GitHub result ingestion."""

from .models import IngestPersistencePort, IngestStatus
from .service import ci_run_id, ingest_ci_run

__all__ = ["IngestPersistencePort", "IngestStatus", "ci_run_id", "ingest_ci_run"]
