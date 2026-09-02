"""Persist one normalized result bundle through an explicit storage port."""
from __future__ import annotations

from collections.abc import Sequence

from app.modules.shared.contracts.findings import NormalizedFinding
from app.modules.shared.contracts.ingest import (
    ARTIFACT_SPECS,
    ResultBundle,
    RunRecord,
    ScannerResult,
)
from app.modules.shared.contracts.source_context import SourceContextPayload

from .ports import ResultPersistencePort


async def persist_result_bundle(
    persistence: ResultPersistencePort,
    record: RunRecord,
    bundle: ResultBundle,
    findings: list[NormalizedFinding],
    source_contexts: Sequence[SourceContextPayload] = (),
) -> None:
    """Stage a complete result graph and its claim, then commit exactly once."""
    try:
        await persistence.add_run(record)
        await persistence.add_scan_job(record)

        for result in sorted(bundle.scanners, key=lambda item: item.kind):
            scanner_run_id = await persistence.create_scanner_run(record.run_id, result)
            if result.status == "completed":
                await persistence.mark_scanner_completed(scanner_run_id)
            elif result.status == "failed":
                await persistence.mark_scanner_failed(
                    scanner_run_id,
                    result.error_code or "scanner failed",
                )
            else:
                await persistence.mark_scanner_skipped(scanner_run_id, result.error_code)

        for spec in ARTIFACT_SPECS:
            content = bundle.artifacts.get(spec.part_name)
            if content is None:
                continue
            scanner_run_id = await persistence.create_scanner_run(
                record.run_id,
                ScannerResult(kind=spec.scanner_kind, status="completed"),
            )
            await persistence.mark_scanner_completed(scanner_run_id)
            await persistence.store_artifact(
                scanner_run_id,
                spec.artifact_kind,
                content,
            )

        if findings:
            await persistence.insert_findings(findings)
        if source_contexts:
            await persistence.insert_source_contexts(record.run_id, source_contexts)
        await persistence.before_commit(record.run_id)
        await persistence.commit()
    except BaseException:
        await persistence.rollback()
        raise
