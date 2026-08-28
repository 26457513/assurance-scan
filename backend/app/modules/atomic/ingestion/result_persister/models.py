"""Contracts for atomic result persistence."""
from app.modules.shared.contracts.findings import NormalizedFinding
from app.modules.shared.contracts.ingest import ResultBundle, RunRecord

__all__ = ["NormalizedFinding", "ResultBundle", "RunRecord"]
