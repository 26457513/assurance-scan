"""Repository for `test_results` (v3)."""
from __future__ import annotations

import json
from typing import Sequence

from sqlalchemy import select

from server.db.models import TestResult
from server.db.repositories.base import BaseRepository


class TestResultRepository(BaseRepository[TestResult]):
    """Atomic operations on `test_results`."""

    model = TestResult

    async def upsert(
        self,
        run_id: str,
        project_path: str,
        fr_id: str,
        test_id: str,
        test_type: str,
        result: str,
        detail: dict[str, object],
    ) -> TestResult:
        # SQLite has UPSERT support; simpler to delete-then-insert per
        # (run, fr, test) since evaluations are recomputed each scan.
        existing = await self.session.execute(
            select(TestResult).where(
                TestResult.run_id == run_id,
                TestResult.fr_id == fr_id,
                TestResult.test_id == test_id,
            )
        )
        for row in existing.scalars().all():
            await self.session.delete(row)

        tr = TestResult(
            run_id=run_id,
            project_path=project_path,
            fr_id=fr_id,
            test_id=test_id,
            test_type=test_type,
            result=result,
            detail_json=json.dumps(detail, sort_keys=True, default=str),
        )
        self.session.add(tr)
        await self._flush()
        return tr

    async def list_for_run(self, run_id: str) -> Sequence[TestResult]:
        result = await self.session.execute(
            select(TestResult)
            .where(TestResult.run_id == run_id)
            .order_by(TestResult.fr_id, TestResult.test_id)
        )
        return result.scalars().all()

    async def list_for_fr(self, run_id: str, fr_id: str) -> Sequence[TestResult]:
        result = await self.session.execute(
            select(TestResult)
            .where(TestResult.run_id == run_id, TestResult.fr_id == fr_id)
            .order_by(TestResult.test_id)
        )
        return result.scalars().all()
