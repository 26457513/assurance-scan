"""Scan orchestrator.

Drives one scan end-to-end:
  1. Resolve catalogue + mapping pack (auto-migrate v1 → v2 if needed)
  2. Snapshot the catalogue
  3. Persist FRs
  4. Spawn each scanner, capture output, insert raw artifact + findings
  5. Map findings → evidence rows via the mapping pack
  6. Compute FR states using the 8-state resolver
  7. Publish findings.json + evidence bundle to the run row

Scanner failures are recorded but don't fail the run.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from server.catalogue import load_catalogue, load_mapping_pack
from server.db.repositories.catalogue_snapshots import CatalogueSnapshotRepository
from server.db.repositories.evidence import EvidenceRepository
from server.db.repositories.findings import FindingRepository
from server.db.repositories.frs import FrRepository
from server.db.repositories.runs import RunRepository
from server.db.repositories.scanner_artifacts import ScannerArtifactRepository
from server.db.repositories.scanner_runs import ScannerRunRepository
from server.evidence import (
    collect_evidence_from_findings,
    compute_states_for_run,
    synthesize_negative_evidence,
)
from server.events import helpers as events
from server.project_tests import TestSuite, discover as discover_tests, run_suite
from server.worker.parsers import parser_for
from server.worker.parsers.junit import parse as parse_junit, to_evidence_records
from server.worker.runner import DockerRunner
from server.worker.scanners import CODE_SCANNERS, ScannerConfig


log = logging.getLogger(__name__)


PR_STRATEGY_SINGLE_FILE_THRESHOLD = 15


class ScanOrchestrator:
    """Runs a scan against a project. One instance per scan."""

    def __init__(
        self,
        session: AsyncSession,
        runner: DockerRunner,
        scanners: tuple[ScannerConfig, ...] = CODE_SCANNERS,
    ) -> None:
        self.session = session
        self.runner = runner
        self.scanners = scanners

        self.runs = RunRepository(session)
        self.scanner_runs = ScannerRunRepository(session)
        self.scanner_artifacts = ScannerArtifactRepository(session)
        self.findings = FindingRepository(session)
        self.snapshots = CatalogueSnapshotRepository(session)
        self.frs_repo = FrRepository(session)
        self.evidence = EvidenceRepository(session)

    async def execute(
        self,
        run_id: str,
        project_path: str,
        options: dict[str, Any],
    ) -> None:
        """Top-level scan lifecycle."""
        try:
            # 1. Resolve catalogue + mapping pack (re-read fresh each scan)
            catalogue = None
            mapping_pack = None
            catalogue_path = options.get("fr_catalog_path")
            if catalogue_path:
                catalogue = load_catalogue(Path(catalogue_path), project_path)
                mapping_pack_path = options.get("mapping_pack_path")
                if mapping_pack_path:
                    mapping_pack = load_mapping_pack(Path(mapping_pack_path))
                else:
                    mapping_pack = load_mapping_pack(None)

                # 2. Snapshot the catalogue (idempotent on content hash)
                snapshot = await self.snapshots.store(
                    project_path=project_path,
                    catalogue=catalogue.doc,
                    catalogue_version=catalogue.doc.get("catalogue_version"),
                )
                # 3. Persist FRs for this snapshot
                await self.frs_repo.bulk_insert_for_snapshot(
                    catalogue_snapshot_id=snapshot.id,
                    project_path=project_path,
                    frs=catalogue.doc.get("frs", []),
                )
                # Link the snapshot to the run
                run = await self.runs.get(run_id)
                if run is not None:
                    run.catalogue_snapshot_id = snapshot.id
                await self.session.flush()

            # 4. Mark running and run scanners
            await self.runs.mark_running(run_id)
            await self.session.commit()

            events.publish_scan_started(
                run_id=run_id,
                project_path=project_path,
                scanner_kinds=[s.kind for s in self.scanners],
            )

            scanner_status: dict[str, str] = {}
            for scanner in self.scanners:
                status = await self._run_scanner(scanner, run_id, project_path)
                scanner_status[scanner.kind] = status

            # 5. Map findings → evidence
            if mapping_pack is not None:
                await collect_evidence_from_findings(
                    session=self.session,
                    run_id=run_id,
                    project_path=project_path,
                    mapping_pack=mapping_pack,
                )

            # 5b. Run project tests (after scanners, before state computation)
            await self._run_project_tests(
                run_id=run_id,
                project_path=project_path,
                mapping_pack=mapping_pack,
            )

            # 5c. Synthesize negative evidence for none_of specs whose
            # scanners ran clean (zero matching findings). This lets FRs
            # with only none_of requirements transition out of to-be-tested.
            if catalogue is not None:
                await synthesize_negative_evidence(
                    session=self.session,
                    run_id=run_id,
                    project_path=project_path,
                    catalogue=catalogue,
                )

            # 6. Compute FR states
            if catalogue is not None:
                await compute_states_for_run(
                    session=self.session,
                    run_id=run_id,
                    project_path=project_path,
                    catalogue=catalogue,
                )

            # 7. Publish findings + evidence bundle
            findings_json = await self._publish_findings(
                run_id, project_path, scanner_status, options
            )
            await self.runs.mark_completed(run_id, findings_json)
            await self.session.commit()
            findings_total = await self.findings.count_for_run(run_id)
            events.publish_scan_completed(run_id, findings_total, "completed")
            log.info("scan complete run_id=%s scanner_status=%s", run_id, scanner_status)

        except Exception as exc:
            log.exception("scan failed run_id=%s", run_id)
            await self.runs.mark_failed(run_id, str(exc))
            await self.session.commit()
            events.publish_scan_completed(run_id, 0, "failed")
            raise

    async def _run_scanner(
        self,
        scanner: ScannerConfig,
        run_id: str,
        project_path: str,
    ) -> str:
        """Run one scanner end-to-end. Returns 'completed' | 'failed'."""
        events.publish_scanner_started(run_id, scanner.kind)
        scanner_run = await self.scanner_runs.create(run_id, scanner.kind)
        await self.scanner_runs.mark_running(scanner_run.id)
        await self.session.commit()

        try:
            result = await self.runner.run(scanner)
            raw = result.stdout if result.ok else _stderr_payload(result)
            await self.scanner_artifacts.store(
                scanner_run_id=scanner_run.id,
                kind=scanner.output_kind if result.ok else "text",
                content=raw,
            )

            if not result.ok:
                err = f"exit={result.returncode} stderr={result.stderr.decode('utf-8', 'replace')[:500]}"
                await self.scanner_runs.mark_failed(scanner_run.id, err)
                await self.session.commit()
                events.publish_scanner_completed(
                    run_id, scanner.kind, "failed", 0, err
                )
                return "failed"

            parsed = parser_for(scanner).parse(raw)
            await self._insert_findings(parsed, run_id)
            await self.scanner_runs.mark_completed(scanner_run.id)
            await self.session.commit()
            events.publish_scanner_completed(run_id, scanner.kind, "completed", len(parsed))
            return "completed"

        except Exception as exc:
            await self.scanner_runs.mark_failed(scanner_run.id, str(exc))
            await self.session.commit()
            events.publish_scanner_completed(
                run_id, scanner.kind, "failed", 0, str(exc)
            )
            return "failed"

    async def _run_project_tests(
        self,
        run_id: str,
        project_path: str,
        mapping_pack,
    ) -> None:
        """Discover and run project test suites; insert evidence rows.

        Test runs are recorded via the same scanner_runs/scanner_artifacts
        tables, using a synthetic scanner_kind of 'project-tests' so the UI
        groups them clearly. Per-test-case results become evidence rows
        for any FR the mapping pack associates them with.
        """
        from pathlib import Path
        suites = discover_tests(Path(project_path))
        if not suites:
            return

        events.publish_scanner_started(run_id, "project-tests")
        scanner_run = await self.scanner_runs.create(run_id, "project-tests")
        await self.scanner_runs.mark_running(scanner_run.id)
        await self.session.commit()

        try:
            all_evidence: list[dict] = []
            mapping_index = self._test_mapping_index(mapping_pack)
            combined_xml_parts: list[bytes] = []
            suite_failures = 0

            for suite in suites:
                result = await run_suite(suite, project_path=project_path)
                if not result.ok and result.returncode not in (0, 5):
                    # pytest returns 5 for "no tests collected"; that's fine.
                    suite_failures += 1
                    log.warning(
                        "test suite %s exited %d: %s",
                        suite.id, result.returncode,
                        result.stderr.decode("utf-8", "replace")[:200],
                    )
                if result.junit_xml:
                    combined_xml_parts.append(result.junit_xml)
                    cases = parse_junit(result.junit_xml, suite_id=suite.id)
                    all_evidence.extend(
                        to_evidence_records(cases, run_id, project_path, mapping_index)
                    )

            # Store the combined JUnit XML as one artifact.
            if combined_xml_parts:
                combined = b"<testsuites>" + b"".join(combined_xml_parts) + b"</testsuites>"
                await self.scanner_artifacts.store(
                    scanner_run_id=scanner_run.id,
                    kind="junit-xml",
                    content=combined,
                )

            if all_evidence:
                await self.evidence.bulk_insert(all_evidence)

            status = "completed" if suite_failures == 0 else "failed"
            if status == "failed":
                await self.scanner_runs.mark_failed(
                    scanner_run.id,
                    f"{suite_failures} suite(s) failed",
                )
            else:
                await self.scanner_runs.mark_completed(scanner_run.id)
            await self.session.commit()
            events.publish_scanner_completed(
                run_id, "project-tests", status, len(all_evidence)
            )

        except Exception as exc:
            await self.scanner_runs.mark_failed(scanner_run.id, str(exc))
            await self.session.commit()
            events.publish_scanner_completed(
                run_id, "project-tests", "failed", 0, str(exc)
            )

    @staticmethod
    def _test_mapping_index(mapping_pack) -> dict[str, str]:
        """Flatten the mapping pack into {name_pattern: fr_id} for tests."""
        if mapping_pack is None:
            return {}
        out: dict[str, str] = {}
        for entry in mapping_pack.mappings:
            src = entry.get("source", {})
            # Test mappings use kind=pytest / jest / etc. and a name_pattern.
            if src.get("kind") in {"pytest", "jest", "go-test", "test"}:
                pattern = src.get("name_pattern")
                fr_id = entry.get("fr_id")
                if pattern and fr_id:
                    out[pattern] = fr_id
        return out

    async def _insert_findings(self, parsed, run_id: str) -> None:
        rows = [
            {
                "run_id": run_id,
                "scanner_kind": p.scanner_kind,
                "rule_id": p.rule_id,
                "severity": p.severity,
                "file_path": p.file_path,
                "line_start": p.line_start,
                "line_end": p.line_end,
                "message": p.message,
                "theme": p.theme,
                "fix_strategy": p.fix_strategy,
                "compliance_tags": list(p.compliance_tags),
                "raw_index": p.raw_index,
            }
            for p in parsed
        ]
        await self.findings.bulk_insert(rows)

    async def _publish_findings(
        self,
        run_id: str,
        project_path: str,
        scanner_status: dict[str, str],
        options: dict[str, Any],
    ) -> str:
        all_rows = await self.findings.list_for_run(run_id, limit=100000)
        findings = [_finding_to_dict(row, i) for i, row in enumerate(all_rows)]

        by_severity = Counter(f["severity"] for f in findings)
        by_scanner = Counter(f["scanner"] for f in findings)
        distinct_files = len({f["file_path"] for f in findings if f["file_path"]})
        pr_strategy = "single" if distinct_files <= PR_STRATEGY_SINGLE_FILE_THRESHOLD else "themed"

        run = await self.runs.get(run_id)
        payload = {
            "schema_version": 1,
            "run_id": run_id,
            "project": project_path,
            "started_at": run.started_at.isoformat() if run else None,
            "completed_at": run.completed_at.isoformat() if run and run.completed_at else None,
            "scanner_status": scanner_status,
            "options": options,
            "pr_strategy": pr_strategy,
            "summary": {
                "total": len(findings),
                "by_severity": dict(by_severity),
                "by_scanner": dict(by_scanner),
                "distinct_files": distinct_files,
            },
            "findings": findings,
        }
        return json.dumps(payload, indent=2, sort_keys=True)


def _finding_to_dict(row: Any, index: int) -> dict[str, Any]:
    return {
        "id": f"F-{index + 1:03d}",
        "scanner": row.scanner_kind,
        "rule_id": row.rule_id,
        "severity": row.severity,
        "file_path": row.file_path,
        "line_start": row.line_start,
        "line_end": row.line_end,
        "message": row.message,
        "theme": row.theme,
        "fix_strategy": row.fix_strategy,
        "compliance_tags": json.loads(row.compliance_tags_json or "[]"),
        "fr_id": None,
    }


def _stderr_payload(result) -> bytes:
    return b"--- scanner failed ---\n" + result.stderr
