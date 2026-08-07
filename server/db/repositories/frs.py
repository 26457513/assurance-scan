"""Repository for `frs`."""
from __future__ import annotations

import json
from typing import Any, Sequence

from sqlalchemy import select

from server.db.models import Fr
from server.db.repositories.base import BaseRepository


class FrRepository(BaseRepository[Fr]):
    """Atomic operations on `frs`."""

    model = Fr

    async def bulk_insert_for_snapshot(
        self,
        catalogue_snapshot_id: str,
        project_path: str,
        frs: Sequence[dict[str, Any]],
    ) -> int:
        for fr in frs:
            self.session.add(
                Fr(
                    catalogue_snapshot_id=catalogue_snapshot_id,
                    project_path=project_path,
                    fr_id=fr["id"],
                    title=fr["title"],
                    description=fr["description"],
                    implemented_by_json=json.dumps(fr.get("implemented_by", [])),
                    required_evidence_json=json.dumps(fr.get("required_evidence", {})),
                    satisfies_json=json.dumps(fr.get("satisfies", [])),
                    depends_on_json=json.dumps(fr.get("depends_on", [])),
                )
            )
        await self._flush()
        return len(frs)

    async def list_for_snapshot(self, catalogue_snapshot_id: str) -> Sequence[Fr]:
        result = await self.session.execute(
            select(Fr)
            .where(Fr.catalogue_snapshot_id == catalogue_snapshot_id)
            .order_by(Fr.fr_id)
        )
        return result.scalars().all()

    async def get_for_snapshot(
        self,
        catalogue_snapshot_id: str,
        fr_id: str,
    ) -> Fr | None:
        result = await self.session.execute(
            select(Fr).where(
                Fr.catalogue_snapshot_id == catalogue_snapshot_id,
                Fr.fr_id == fr_id,
            )
        )
        return result.scalars().first()
