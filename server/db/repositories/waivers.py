"""Repository for `waivers`."""
from __future__ import annotations

import datetime as dt
from typing import Sequence

from sqlalchemy import select

from server.db.models import Waiver
from server.db.repositories.base import BaseRepository


class WaiverRepository(BaseRepository[Waiver]):
    """Atomic operations on `waivers`."""

    model = Waiver

    async def create(
        self,
        project_path: str,
        fr_id: str,
        reason: str,
        waived_by: str,
        expires_at: dt.datetime | None = None,
    ) -> Waiver:
        waiver = Waiver(
            project_path=project_path,
            fr_id=fr_id,
            reason=reason,
            waived_by=waived_by,
            waived_at=dt.datetime.now(dt.timezone.utc),
            expires_at=expires_at,
        )
        self.session.add(waiver)
        await self._flush()
        return waiver

    async def list_for_project(
        self,
        project_path: str,
        include_expired: bool = False,
    ) -> Sequence[Waiver]:
        stmt = select(Waiver).where(Waiver.project_path == project_path)
        if not include_expired:
            now = dt.datetime.now(dt.timezone.utc)
            stmt = stmt.where(
                (Waiver.expires_at.is_(None)) | (Waiver.expires_at > now)
            )
        stmt = stmt.order_by(Waiver.waived_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_for_fr(
        self,
        project_path: str,
        fr_id: str,
        include_expired: bool = False,
    ) -> Sequence[Waiver]:
        stmt = select(Waiver).where(
            Waiver.project_path == project_path,
            Waiver.fr_id == fr_id,
        )
        if not include_expired:
            now = dt.datetime.now(dt.timezone.utc)
            stmt = stmt.where(
                (Waiver.expires_at.is_(None)) | (Waiver.expires_at > now)
            )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def delete(self, waiver_id: int) -> bool:
        waiver = await self.session.get(Waiver, waiver_id)
        if waiver is None:
            return False
        await self.session.delete(waiver)
        await self._flush()
        return True
