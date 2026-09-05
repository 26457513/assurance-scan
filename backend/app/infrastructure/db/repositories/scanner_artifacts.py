"""Repository for the `scanner_artifacts` table.

Stores raw scanner output as gzip-compressed BLOBs so the DB is the
single source of truth (no file artifacts in the project repo).
"""
from __future__ import annotations

import gzip
import hashlib

from sqlalchemy import select

from app.infrastructure.db.models import ScannerArtifact, ScannerRun
from app.infrastructure.db.repositories.base import BaseRepository


def _compress(content: bytes) -> tuple[bytes, str, int]:
    """Returns (gzip_blob, sha256_hex, uncompressed_size)."""
    raw_hash = hashlib.sha256(content).hexdigest()
    blob = gzip.compress(content, compresslevel=6)
    return blob, f"sha256:{raw_hash}", len(content)


class ScannerArtifactRepository(BaseRepository[ScannerArtifact]):
    """Atomic operations on `scanner_artifacts`."""

    model = ScannerArtifact

    async def store(
        self,
        scanner_run_id: int,
        kind: str,
        content: bytes,
    ) -> ScannerArtifact:
        """Compress and store scanner output. `kind` is 'sarif' | 'json' | 'text'."""
        blob, content_hash, size = _compress(content)
        artifact = ScannerArtifact(
            scanner_run_id=scanner_run_id,
            kind=kind,
            content_blob=blob,
            content_hash=content_hash,
            size_bytes=size,
        )
        self.session.add(artifact)
        await self._flush()
        return artifact

    async def get_for_scanner_run(self, scanner_run_id: int) -> ScannerArtifact | None:
        result = await self.session.execute(
            select(ScannerArtifact).where(
                ScannerArtifact.scanner_run_id == scanner_run_id
            )
        )
        return result.scalars().first()

    async def list_published_for_run(
        self,
        run_id: str,
    ) -> list[tuple[ScannerRun, ScannerArtifact | None]]:
        """Return generated result artifacts, including expired payloads."""
        result = await self.session.execute(
            select(ScannerRun, ScannerArtifact)
            .outerjoin(ScannerArtifact, ScannerArtifact.scanner_run_id == ScannerRun.id)
            .where(
                ScannerRun.run_id == run_id,
                ScannerRun.scanner_kind.startswith("assurance-scan/"),
            )
            .order_by(ScannerRun.scanner_kind)
        )
        return list(result.tuples().all())

    @staticmethod
    def decompress(artifact: ScannerArtifact) -> bytes:
        """Decompress a stored BLOB back to the original scanner output."""
        return gzip.decompress(artifact.content_blob)
