"""Repository for `compliance_mappings`."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from server.db.models import ComplianceMapping
from server.db.repositories.base import BaseRepository


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
            loaded_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        self.session.add(new)
        await self._flush()
        return new

    async def get_for_project(self, project_path: str) -> ComplianceMapping | None:
        result = await self.session.execute(
            select(ComplianceMapping)
            .where(ComplianceMapping.project_path == project_path)
            .order_by(ComplianceMapping.loaded_at.desc())
            .limit(1)
        )
        return result.scalars().first()
