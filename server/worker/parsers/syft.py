"""Parse Syft CycloneDX SBOM output.

Syft produces an SBOM (inventory), not findings. We store the raw
artifact but emit zero rows into the `findings` table. The SBOM is
queryable separately via `/api/scans/{run_id}/artifacts/syft`.
"""
from __future__ import annotations

from server.worker.parsers.base import FindingParser, ParsedFinding


class SyftSbomParser(FindingParser):
    """Syft runs but emits no findings (SBOM-only)."""

    def parse(self, raw: bytes) -> list[ParsedFinding]:
        return []
