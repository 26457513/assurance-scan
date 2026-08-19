"""Repository for `catalogue_snapshots`."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select

from server.db.models import CatalogueSnapshot
from server.db.repositories.base import BaseRepository


def _snapshot_id(project_path: str, content_hash: str) -> str:
    digest = hashlib.sha1(f"{project_path}|{content_hash}".encode()).hexdigest()[:16]
    return f"snap_{digest}"


class CatalogueSnapshotRepository(BaseRepository[CatalogueSnapshot]):
    """Atomic operations on `catalogue_snapshots`."""

    model = CatalogueSnapshot

    async def store(
        self,
        project_path: str,
        catalogue: dict[str, Any],
        catalogue_version: str | None,
        tag: str | None = None,
    ) -> CatalogueSnapshot:
        from server.vcs import git_head

        body = json.dumps(catalogue, sort_keys=True)
        content_hash = f"sha256:{hashlib.sha256(body.encode()).hexdigest()}"
        snapshot_id = _snapshot_id(project_path, content_hash)
        commit = await git_head(project_path)

        existing = await self.session.get(CatalogueSnapshot, snapshot_id)
        if existing is not None:
            if existing.source_commit_sha is None and commit:
                existing.source_commit_sha = commit
                await self._flush()
            return existing

        snapshot = CatalogueSnapshot(
            tag=tag or None,
            id=snapshot_id,
            project_path=project_path,
            catalogue_version=catalogue_version,
            snapshot_json=body,
            content_hash=content_hash,
            source_commit_sha=commit,
        )
        self.session.add(snapshot)
        await self._flush()
        return snapshot

    async def get(self, snapshot_id: str) -> CatalogueSnapshot | None:
        return await self.session.get(CatalogueSnapshot, snapshot_id)
