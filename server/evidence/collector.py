"""Map scanner findings to Evidence rows using the evidence-mapping pack.

For Phase 1, mapping pack entries with matching (scanner_kind, rule_id)
produce an Evidence record with `result='fail'` for the mapped FR.
Pass-result evidence requires manual attestation or generated tests —
those flow in via the imported/manual evidence types, not findings.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from server.db.repositories.evidence import EvidenceRepository
from server.db.repositories.findings import FindingRepository
from server.catalogue.loader import LoadedMappingPack


log = logging.getLogger(__name__)


async def collect_evidence_from_findings(
    session: AsyncSession,
    run_id: str,
    project_path: str,
    mapping_pack: LoadedMappingPack,
) -> int:
    """For each finding whose (scanner_kind, rule_id) maps to an FR, insert an
    Evidence row. Returns the count of evidence records inserted."""
    findings_repo = FindingRepository(session)
    evidence_repo = EvidenceRepository(session)

    # Build (scanner_kind, rule_id) -> fr_id index
    mapping_index: dict[tuple[str, str], str] = {}
    for entry in mapping_pack.mappings:
        src = entry.get("source", {})
        kind = src.get("kind")
        rule_id = src.get("rule_id")
        fr_id = entry.get("fr_id")
        if kind and rule_id and fr_id:
            mapping_index[(kind, rule_id)] = fr_id

    if not mapping_index:
        return 0

    findings = await findings_repo.list_for_run(run_id, limit=100000)

    inserted = 0
    for finding in findings:
        key = (finding.scanner_kind, finding.rule_id or "")
        fr_id = mapping_index.get(key)
        if not fr_id:
            continue

        await evidence_repo.insert(
            {
                "project_path": project_path,
                "fr_id": fr_id,
                "run_id": run_id,
                "type": "scanner-result",
                "source": {
                    "kind": finding.scanner_kind,
                    "rule_id": finding.rule_id,
                    "run_kind": "worker-run",
                    "run_id": run_id,
                },
                "result": "fail",  # Phase 1: a finding's existence == fail
                "artifact_ref": f"scanner_artifacts.finding_id={finding.id}",
                "notes": finding.message[:500],
            }
        )
        inserted += 1

    log.info(
        "evidence collected: %d rows from %d findings (%d mappings)",
        inserted,
        len(findings),
        len(mapping_index),
    )
    return inserted
