"""Repository for `agent_actions` (audit log)."""
from __future__ import annotations

import json
from typing import Any, Sequence

from sqlalchemy import select

from app.infrastructure.db.models import AgentAction
from app.infrastructure.db.repositories.base import BaseRepository


class AgentActionRepository(BaseRepository[AgentAction]):
    """Atomic operations on `agent_actions`."""

    model = AgentAction

    async def record(
        self,
        action_kind: str,
        actor: str,
        project_path: str | None = None,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AgentAction:
        action = AgentAction(
            project_path=project_path,
            run_id=run_id,
            action_kind=action_kind,
            actor=actor,
            payload_json=json.dumps(payload or {}, sort_keys=True),
        )
        self.session.add(action)
        await self._flush()
        return action

    async def list_for_run(self, run_id: str) -> Sequence[AgentAction]:
        result = await self.session.execute(
            select(AgentAction)
            .where(AgentAction.run_id == run_id)
            .order_by(AgentAction.occurred_at)
        )
        return result.scalars().all()
