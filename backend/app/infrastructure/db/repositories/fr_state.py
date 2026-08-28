"""Repository for `fr_state`."""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Sequence

from sqlalchemy import select

from app.infrastructure.db.models import FrState
from app.infrastructure.db.repositories.base import BaseRepository


class FrStateRepository(BaseRepository[FrState]):
    """Atomic operations on `fr_state`."""

    model = FrState

    async def upsert(
        self,
        project_path: str,
        fr_id: str,
        run_id: str,
        state: str,
        reason: dict[str, Any],
    ) -> FrState:
        row = FrState(
            project_path=project_path,
            fr_id=fr_id,
            run_id=run_id,
            state=state,
            reason_json=json.dumps(reason, sort_keys=True),
            computed_at=dt.datetime.now(dt.timezone.utc),
        )
        self.session.add(row)
        await self._flush()
        return row

    async def delete_for_run(self, run_id: str) -> int:
        result = await self.session.execute(
            select(FrState).where(FrState.run_id == run_id)
        )
        rows = result.scalars().all()
        for row in rows:
            await self.session.delete(row)
        return len(rows)

    async def list_for_run(self, run_id: str) -> Sequence[FrState]:
        result = await self.session.execute(
            select(FrState)
            .where(FrState.run_id == run_id)
            .order_by(FrState.fr_id)
        )
        return result.scalars().all()

    async def list_for_run_in_state(
        self,
        run_id: str,
        states: Sequence[str],
    ) -> Sequence[FrState]:
        if not states:
            return []
        result = await self.session.execute(
            select(FrState)
            .where(FrState.run_id == run_id, FrState.state.in_(states))
            .order_by(FrState.fr_id)
        )
        return result.scalars().all()
