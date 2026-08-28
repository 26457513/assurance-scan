"""Repository for `evidence`."""
from __future__ import annotations

import json
from typing import Any, Sequence

from sqlalchemy import select

from app.infrastructure.db.models import Evidence
from app.infrastructure.db.repositories.base import BaseRepository


class EvidenceRepository(BaseRepository[Evidence]):
    """Atomic operations on `evidence`."""

    model = Evidence

    async def insert(self, item: dict[str, Any]) -> Evidence:
        ev = Evidence(
            project_path=item["project_path"],
            fr_id=item["fr_id"],
            run_id=item["run_id"],
            type=item["type"],
            source_json=json.dumps(item.get("source", {})),
            result=item["result"],
            artifact_ref=item.get("artifact_ref"),
            artifact_hash=item.get("artifact_hash"),
            confidence=item.get("confidence"),
            notes=item.get("notes"),
        )
        self.session.add(ev)
        await self._flush()
        return ev

    async def bulk_insert(self, items: Sequence[dict[str, Any]]) -> int:
        for item in items:
            await self.insert(item)
        return len(items)

    async def list_for_run(self, run_id: str) -> Sequence[Evidence]:
        result = await self.session.execute(
            select(Evidence)
            .where(Evidence.run_id == run_id)
            .order_by(Evidence.fr_id, Evidence.type)
        )
        return result.scalars().all()

    async def list_for_fr(self, project_path: str, fr_id: str, run_id: str) -> Sequence[Evidence]:
        result = await self.session.execute(
            select(Evidence)
            .where(
                Evidence.project_path == project_path,
                Evidence.fr_id == fr_id,
                Evidence.run_id == run_id,
            )
            .order_by(Evidence.collected_at)
        )
        return result.scalars().all()

    async def delete_for_run(self, run_id: str) -> int:
        result = await self.session.execute(
            select(Evidence).where(Evidence.run_id == run_id)
        )
        rows = result.scalars().all()
        for row in rows:
            await self.session.delete(row)
        return len(rows)
