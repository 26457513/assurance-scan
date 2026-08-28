"""Persist one normalized result bundle through an explicit storage port."""
from __future__ import annotations

from app.modules.shared.contracts.findings import NormalizedFinding
from app.modules.shared.contracts.ingest import ARTIFACT_SPECS, ResultBundle, RunRecord

from .ports import ResultPersistencePort


async def persist_result_bundle(
    persistence: ResultPersistencePort,
    record: RunRecord,
    bundle: ResultBundle,
    findings: list[NormalizedFinding],
) -> None:
    """Stage a run and all child records, then commit exactly once."""
    await persistence.add_run(record)
    await persistence.add_scan_job(record)

    if bundle.payload is not None:
        for kind, status in sorted(bundle.payload.get("scanner_status", {}).items()):
            scanner_run_id = await persistence.create_scanner_run(record.run_id, kind)
            if status == "ok":
                await persistence.mark_scanner_completed(scanner_run_id)
            else:
                await persistence.mark_scanner_failed(scanner_run_id, status)

        for spec in ARTIFACT_SPECS:
            content = bundle.blobs.get(spec.suffix)
            if content is None:
                continue
            scanner_run_id = await persistence.create_scanner_run(
                record.run_id, f"assurance-scan/{spec.suffix}"
            )
            await persistence.mark_scanner_completed(scanner_run_id)
            await persistence.store_artifact(
                scanner_run_id,
                spec.artifact_kind,
                content,
            )

        if findings:
            await persistence.insert_findings(findings)

    await persistence.commit()
