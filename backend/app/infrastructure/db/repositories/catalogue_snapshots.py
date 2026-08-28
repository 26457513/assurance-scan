"""Repository for `catalogue_snapshots`."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.infrastructure.db.models import CatalogueSnapshot
from app.infrastructure.db.repositories.base import BaseRepository


def _snapshot_id(project_path: str, content_hash: str) -> str:
    # This is a persisted deterministic identity, not a security digest. Changing
    # the algorithm would change existing snapshot IDs and break their references.
    digest = hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
        f"{project_path}|{content_hash}".encode()
    ).hexdigest()[:16]
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
        source_commit: str | None = None,
        source_branch: str | None = None,
    ) -> CatalogueSnapshot:
        from app.vcs import git_branch, git_head

        body = json.dumps(catalogue, sort_keys=True)
        content_hash = f"sha256:{hashlib.sha256(body.encode()).hexdigest()}"
        snapshot_id = _snapshot_id(project_path, content_hash)
        # Caller-supplied provenance (the agent read the checkout) wins;
        # fall back to the server's own git view when it has the repo.
        commit = source_commit or await git_head(project_path)
        branch = source_branch or await git_branch(project_path)

        existing = await self.session.get(CatalogueSnapshot, snapshot_id)
        if existing is not None:
            changed = False
            if existing.source_commit_sha is None and commit:
                existing.source_commit_sha = commit
                changed = True
            if existing.source_branch is None and branch:
                existing.source_branch = branch
                changed = True
            if changed:
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
            source_branch=branch,
        )
        self.session.add(snapshot)
        await self._flush()
        return snapshot

    async def get(self, snapshot_id: str) -> CatalogueSnapshot | None:
        return await self.session.get(CatalogueSnapshot, snapshot_id)
