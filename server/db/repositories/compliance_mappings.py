"""Repository for `compliance_mappings` (+ immutable snapshots)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from sqlalchemy import select

from server.db.models import CatalogueSnapshot, ComplianceMapping, ComplianceMappingSnapshot
from server.db.repositories.base import BaseRepository


def _snapshot_id(project_path: str, content_hash: str) -> str:
    digest = hashlib.sha1(f"{project_path}|{content_hash}".encode()).hexdigest()[:16]
    return f"map_{digest}"


class ComplianceMappingRepository(BaseRepository[ComplianceMapping]):
    """Atomic operations on `compliance_mappings`."""

    model = ComplianceMapping

    async def upsert(
        self,
        project_path: str,
        content_hash: str,
        mapping_doc: dict[str, Any],
    ) -> ComplianceMapping:
        # Delete any existing rows for this project (we keep only the latest).
        existing = await self.session.execute(
            select(ComplianceMapping).where(
                ComplianceMapping.project_path == project_path
            )
        )
        for row in existing.scalars().all():
            await self.session.delete(row)

        new = ComplianceMapping(
            project_path=project_path,
            content_hash=content_hash,
            mapping_doc_json=json.dumps(mapping_doc, sort_keys=True),
            loaded_at=dt.datetime.now(dt.timezone.utc),
        )
        self.session.add(new)
        await self._flush()
        await self.store_snapshot(project_path, content_hash, mapping_doc)
        return new

    async def store_snapshot(
        self,
        project_path: str,
        content_hash: str,
        mapping_doc: dict[str, Any],
    ) -> ComplianceMappingSnapshot:
        """Record an immutable copy, pinning the catalogue + packs it targets."""
        snapshot_id = _snapshot_id(project_path, content_hash)
        existing = await self.session.get(ComplianceMappingSnapshot, snapshot_id)
        if existing is not None:
            return existing

        packs: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for entry in mapping_doc.get("mappings", []):
            ruleset = entry.get("ruleset", "")
            if not ruleset:
                continue
            key = (ruleset, entry.get("version", ""))
            if key in seen:
                continue
            seen.add(key)
            packs.append({"ruleset": ruleset, "version": entry.get("version", "")})

        catalogue_hash: str | None = (
            await self.session.execute(
                select(CatalogueSnapshot.content_hash)
                .where(CatalogueSnapshot.project_path == project_path)
                .order_by(CatalogueSnapshot.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        snapshot = ComplianceMappingSnapshot(
            id=snapshot_id,
            project_path=project_path,
            content_hash=content_hash,
            catalogue_content_hash=catalogue_hash,
            packs_json=json.dumps(packs, sort_keys=True),
            mapping_doc_json=json.dumps(mapping_doc, sort_keys=True),
            loaded_at=dt.datetime.now(dt.timezone.utc),
        )
        self.session.add(snapshot)
        await self._flush()
        return snapshot

    async def get_snapshot(self, snapshot_id: str) -> ComplianceMappingSnapshot | None:
        return await self.session.get(ComplianceMappingSnapshot, snapshot_id)

    async def list_snapshots(self, project_path: str) -> list[ComplianceMappingSnapshot]:
        result = await self.session.execute(
            select(ComplianceMappingSnapshot)
            .where(ComplianceMappingSnapshot.project_path == project_path)
            .order_by(ComplianceMappingSnapshot.loaded_at.desc())
        )
        return list(result.scalars().all())

    async def get_for_project(self, project_path: str) -> ComplianceMapping | None:
        result = await self.session.execute(
            select(ComplianceMapping)
            .where(ComplianceMapping.project_path == project_path)
            .order_by(ComplianceMapping.loaded_at.desc())
            .limit(1)
        )
        return result.scalars().first()
