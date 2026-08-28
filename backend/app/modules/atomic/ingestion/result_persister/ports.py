"""Ports required to persist a normalized result bundle."""

from __future__ import annotations

from typing import Protocol, Sequence

from app.modules.shared.contracts.findings import NormalizedFinding
from app.modules.shared.contracts.ingest import RunRecord


class ResultPersistencePort(Protocol):
    """Storage operations used by the atomic persistence service."""

    async def add_run(self, record: RunRecord) -> None: ...

    async def add_scan_job(self, record: RunRecord) -> None: ...

    async def create_scanner_run(self, run_id: str, scanner_kind: str) -> int: ...

    async def mark_scanner_completed(self, scanner_run_id: int) -> None: ...

    async def mark_scanner_failed(self, scanner_run_id: int, error: str) -> None: ...

    async def store_artifact(
        self,
        scanner_run_id: int,
        artifact_kind: str,
        content: bytes,
    ) -> None: ...

    async def insert_findings(self, findings: Sequence[NormalizedFinding]) -> None: ...

    async def commit(self) -> None: ...


__all__ = ["ResultPersistencePort"]
