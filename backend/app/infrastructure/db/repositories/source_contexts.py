"""Persistence and lookup operations for finding source contexts."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from sqlalchemy import select

from app.infrastructure.db.models import Finding, SourceContext, SourceContextFinding
from app.infrastructure.db.repositories.base import BaseRepository
from app.modules.shared.contracts.source_context import SourceContextPayload


class SourceContextRepository(BaseRepository[SourceContext]):
    """Atomic operations for deduplicated source windows and finding links."""

    model = SourceContext

    async def bulk_insert(
        self,
        run_id: str,
        contexts: Sequence[SourceContextPayload],
    ) -> int:
        """Insert contexts and link them to already-flushed keyed findings."""

        if not contexts:
            return 0
        keys = {
            key
            for context in contexts
            for key in context.get("finding_keys", [])
        }
        rows = (
            await self.session.execute(
                select(Finding).where(
                    Finding.run_id == run_id,
                    Finding.finding_key.in_(keys),
                )
            )
        ).scalars().all()
        findings_by_key: Mapping[str, Finding] = {
            row.finding_key: row for row in rows if row.finding_key is not None
        }
        if set(findings_by_key) != keys:
            raise ValueError("source context finding keys were not persisted")

        pending: list[tuple[SourceContext, SourceContextPayload]] = []
        for payload in contexts:
            context = SourceContext(
                run_id=run_id,
                context_key=payload["context_key"],
                available=payload["available"],
                provider=payload["provider"],
                file_path=payload.get("path"),
                window_start=payload.get("window_start"),
                window_end=payload.get("window_end"),
                highlight_start=payload.get("highlight_start"),
                highlight_end=payload.get("highlight_end"),
                highlight_truncated=payload.get("highlight_truncated", False),
                lines_json=json.dumps(
                    payload.get("lines", []),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                source_hash=payload.get("source_hash"),
                redaction_version=payload["redaction_version"],
                redaction_changed=payload["redaction_changed"],
                unavailable_reason=payload.get("unavailable_reason"),
            )
            self.session.add(context)
            pending.append((context, payload))
        await self._flush()
        for context, payload in pending:
            for finding_key in payload["finding_keys"]:
                self.session.add(
                    SourceContextFinding(
                        context_id=context.id,
                        finding_id=findings_by_key[finding_key].id,
                    )
                )
        await self._flush()
        return len(contexts)

    async def get_for_finding(self, run_id: str, finding_id: int) -> SourceContext | None:
        """Return the uploaded context linked to one finding in one run."""

        result = await self.session.execute(
            select(SourceContext)
            .join(SourceContextFinding, SourceContextFinding.context_id == SourceContext.id)
            .where(
                SourceContext.run_id == run_id,
                SourceContextFinding.finding_id == finding_id,
            )
        )
        return result.scalar_one_or_none()


__all__ = ["SourceContextRepository"]
