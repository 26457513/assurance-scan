"""Synthesize 'negative evidence' for `none_of` specs whose scanners ran
clean.

Problem this solves: an FR with `none_of: [{scanner-result, source_kind=X,
rule_id=Y}]` should be `passed` when scanner X ran and didn't find rule Y.
But the existing evidence collector only inserts evidence when a scanner
FINDS something matching the mapping pack. With zero findings, zero
evidence exists, and the state machine drops the FR into `to-be-tested`.

Fix: after scanner evidence is collected, walk every FR's `none_of` specs
and synthesize one `pass` evidence record per spec where the referenced
scanner_kind actually ran (completed or failed) and produced zero
matching findings. The state machine sees the evidence, the `none_of`
check sees no matching failures, the FR is promoted to `passed`.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.catalogue.loader import LoadedCatalogue
from server.db.models import Finding, ScannerRun
from server.db.repositories.evidence import EvidenceRepository


log = logging.getLogger(__name__)


async def synthesize_negative_evidence(
    session: AsyncSession,
    run_id: str,
    project_path: str,
    catalogue: LoadedCatalogue,
) -> int:
    """Insert pass-evidence for `none_of` specs that didn't fire. Returns count."""
    # Index scanner runs by kind so we know which scanners actually executed.
    scanner_kinds_ran: set[str] = set()
    scanner_run_rows = (await session.execute(
        select(ScannerRun).where(ScannerRun.run_id == run_id)
    )).scalars().all()
    for sr in scanner_run_rows:
        # Treat 'completed' as "ran". 'failed' scanners may have produced
        # partial output but we can't trust their absence-of-findings signal.
        if sr.status == "completed":
            scanner_kinds_ran.add(sr.scanner_kind)

    if not scanner_kinds_ran:
        return 0

    # Index existing findings by (scanner_kind, rule_id) for quick lookup.
    finding_index: dict[tuple[str, str], int] = {}
    finding_rows = (await session.execute(
        select(Finding.scanner_kind, Finding.rule_id).where(Finding.run_id == run_id)
    )).all()
    for kind, rule_id in finding_rows:
        if rule_id:
            finding_index[(kind, rule_id)] = finding_index.get((kind, rule_id), 0) + 1

    repo = EvidenceRepository(session)
    inserted = 0

    for fr in catalogue.doc.get("frs", []):
        fr_id = fr["id"]
        required = fr.get("required_evidence", {}) or {}
        none_of_specs = required.get("none_of", []) or []

        for spec in none_of_specs:
            if spec.get("type") != "scanner-result":
                continue
            source_kind = spec.get("source_kind")
            rule_id = spec.get("rule_id")
            if not source_kind or not rule_id:
                continue
            if source_kind not in scanner_kinds_ran:
                # Scanner didn't run at all — can't claim absence of findings.
                continue
            if (source_kind, rule_id) in finding_index:
                # Scanner found the bad thing — that's evidence the FR fails,
                # which the existing collector already inserted via mapping pack.
                continue

            # Synthesize: scanner ran, produced zero matching findings.
            await repo.insert({
                "project_path": project_path,
                "fr_id": fr_id,
                "run_id": run_id,
                "type": "scanner-result",
                "source": {
                    "kind": source_kind,
                    "rule_id": rule_id,
                    "run_kind": "worker-run",
                    "run_id": run_id,
                    "synthesized": True,
                    "note": "scanner ran with zero matching findings",
                },
                "result": "pass",
                "notes": f"{source_kind} ran clean for rule {rule_id}",
            })
            inserted += 1

    if inserted:
        log.info("synthesized %d negative-evidence records for run %s", inserted, run_id)
    return inserted
