"""Repository for the `findings` table.

Findings are normalized per-issue rows extracted from scanner artifacts.
Bulk-inserted after the parser runs.
"""
from __future__ import annotations

import json
from typing import Any, Sequence

from sqlalchemy import select

from server.db.models import Finding
from server.db.repositories.base import BaseRepository


class FindingRepository(BaseRepository[Finding]):
    """Atomic operations on `findings`."""

    model = Finding

    async def bulk_insert(self, items: Sequence[dict[str, Any]]) -> int:
        """Insert a batch of finding dicts. Returns count inserted."""
        if not items:
            return 0
        for item in items:
            compliance_tags = item.get("compliance_tags") or []
            self.session.add(
                Finding(
                    run_id=item["run_id"],
                    scanner_kind=item["scanner_kind"],
                    rule_id=item.get("rule_id"),
                    severity=item["severity"],
                    file_path=item.get("file_path"),
                    line_start=item.get("line_start"),
                    line_end=item.get("line_end"),
                    message=item["message"],
                    theme=item.get("theme"),
                    fix_strategy=item.get("fix_strategy"),
                    compliance_tags_json=json.dumps(compliance_tags),
                )
            )
        await self._flush()
        return len(items)

    async def list_for_run(
        self,
        run_id: str,
        severity: str | None = None,
        limit: int = 1000,
    ) -> Sequence[Finding]:
        stmt = select(Finding).where(Finding.run_id == run_id)
        if severity:
            stmt = stmt.where(Finding.severity == severity.upper())
        stmt = stmt.order_by(Finding.severity, Finding.id).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_for_run(self, run_id: str) -> int:
        result = await self.session.execute(
            select(Finding).where(Finding.run_id == run_id)
        )
        return len(result.scalars().all())
