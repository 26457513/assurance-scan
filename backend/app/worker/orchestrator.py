"""Scan orchestrator (v3).

Drives one scan end-to-end:
  1. Resolve catalogue (v3 — no mapping pack, no migration)
  2. Snapshot the catalogue
  3. Persist FRs
  4. Spawn each scanner, capture output, store raw artifact + findings
  5. Run project tests (capture JUnit XML)
  6. Evaluate tests per FR + compute FR states
  7. Publish findings.json

Scanner failures are recorded but don't fail the run.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.catalogue import LoadedCatalogue, load_catalogue
from app.infrastructure.db.repositories.catalogue_snapshots import CatalogueSnapshotRepository
from app.infrastructure.db.repositories.compliance_mappings import ComplianceMappingRepository
from app.infrastructure.db.repositories.findings import FindingRepository
from app.infrastructure.db.repositories.frs import FrRepository
from app.infrastructure.db.repositories.runs import RunRepository
from app.infrastructure.db.repositories.scanner_artifacts import ScannerArtifactRepository
from app.infrastructure.db.repositories.scanner_runs import ScannerRunRepository
from app.evidence import evaluate_tests_and_compute_states
from app.events import helpers as events
from app.mapping import load_mapping
from app.modules.atomic.platform.docker_port import DockerRunner
from app.modules.atomic.scanning.scanner_catalog import CODE_SCANNERS, ScannerConfig
from app.project_tests import discover as discover_tests, run_suite
from app.state.matcher import TestCaseRecord
from app.modules.atomic.scanning.finding_parser import parser_for
from app.modules.atomic.scanning.test_result_parser import parse as parse_junit
from app.vcs import git_branch, git_head, git_worktree_dirty


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
        self.mappings_repo = ComplianceMappingRepository(session)

    async def execute(
        self,
        run_id: str,
        project_id: int,
        local_path: str,
        options: dict[str, Any],
    ) -> None:
        """Top-level scan lifecycle."""
        try:
            catalogue = None
            catalogue_path = options.get("fr_catalog_path")

            # Try reading catalogue from file first.
            if catalogue_path and Path(catalogue_path).exists():
                catalogue = load_catalogue(Path(catalogue_path), local_path)
                snapshot = await self.snapshots.store(
                    project_id=project_id,
                    catalogue=catalogue.doc,
                    catalogue_version=catalogue.doc.get("catalogue_version"),
                    source_root=local_path,
                )
                await self.frs_repo.bulk_insert_for_snapshot(
                    catalogue_snapshot_id=snapshot.id,
                    frs=catalogue.doc.get("frs", []),
                )
                run = await self.runs.get(run_id)
                if run is not None:
                    run.catalogue_snapshot_id = snapshot.id
                await self.session.flush()

            # If no file was found, check DB for a previously-saved snapshot
            # (via save_catalogue MCP tool). Use the latest snapshot for this
            # project.
            if catalogue is None:
                from app.infrastructure.db.models import CatalogueSnapshot
                from sqlalchemy import select as sa_select
                snap_row = (await self.session.execute(
                    sa_select(CatalogueSnapshot)
                    .where(CatalogueSnapshot.project_id == project_id)
                    .order_by(CatalogueSnapshot.created_at.desc())
                    .limit(1)
                )).scalars().first()
                if snap_row:
                    import json as _json
                    catalogue_doc = _json.loads(snap_row.snapshot_json)
                    catalogue = LoadedCatalogue(
                        doc=catalogue_doc,
                        path=Path("(db-snapshot)"),
                        project_path=local_path,
                        content_hash=snap_row.content_hash,
                        generated_at=snap_row.created_at,
                    )
                    run = await self.runs.get(run_id)
                    if run is not None:
                        run.catalogue_snapshot_id = snap_row.id
                    await self.session.flush()
                    log.info(
                        "loaded catalogue from DB snapshot %s (project=%s, %d FRs)",
                        snap_row.id, project_id, len(catalogue_doc.get("frs", [])),
                    )

            # Load the compliance mapping.
            # Check DB first (saved via save_mapping MCP tool).
            mapping_row = await self.mappings_repo.get_for_project(project_id)
            mapping_path = options.get("compliance_mapping_path")
            if not mapping_path and catalogue_path:
                candidate = Path(catalogue_path).parent / "fr-compliance-mapping.json"
                if candidate.exists():
                    mapping_path = str(candidate)

            mapping_hash: str | None = None
            if mapping_row is not None:
                # Use DB-stored mapping.
                mapping_hash = mapping_row.content_hash
            elif mapping_path and Path(mapping_path).exists():
                try:
                    mapping = load_mapping(Path(mapping_path), local_path)
                    await self.mappings_repo.upsert(
                        project_id=project_id,
                        content_hash=mapping.content_hash,
                        mapping_doc=mapping.doc,
                    )
                    mapping_hash = mapping.content_hash
                    log.info(
                        "loaded compliance mapping: %d entries (hash=%s)",
                        len(mapping.mappings),
                        mapping.content_hash[:16],
                    )
                except Exception as exc:
                    log.warning("could not load compliance mapping: %s", exc)

            # Pin the mapping hash on the run so historical runs stay
            # interpretable when the project's mapping is later replaced.
            run = await self.runs.get(run_id)
            if run is not None:
                run.mapping_hash = mapping_hash
            await self.session.flush()

            head = await git_head(local_path)
            branch = await git_branch(local_path)
            dirty = await git_worktree_dirty(local_path)
            run = await self.runs.get(run_id)
            if run is not None:
                run.commit_sha = head
                run.git_object_format = (
                    "sha1" if head and len(head) == 40 else "sha256" if head and len(head) == 64 else None
                )
                run.git_branch = branch
                run.working_tree_dirty = dirty

            await self.runs.mark_running(run_id)
            await self.session.commit()

            events.publish_scan_started(
                run_id=run_id,
                project_id=project_id,
                scanner_kinds=[s.kind for s in self.scanners],
            )

            scanner_status: dict[str, str] = {}
            for scanner in self.scanners:
                status = await self._run_scanner(scanner, run_id)
                scanner_status[scanner.kind] = status

            test_cases = await self._run_project_tests(
                run_id=run_id,
                project_path=local_path,
            )

            if catalogue is not None:
                await evaluate_tests_and_compute_states(
                    session=self.session,
                    run_id=run_id,
                    project_id=project_id,
                    catalogue=catalogue,
                    test_cases=test_cases,
                )

            findings_json = await self._publish_findings(
                run_id, project_id, scanner_status, options
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
    ) -> str:
        events.publish_scanner_started(run_id, scanner.kind)
        scanner_run = await self.scanner_runs.create(
            run_id,
            scanner.kind,
            image_reference=scanner.image,
        )
        await self.scanner_runs.mark_running(scanner_run.id)
        await self.session.commit()

        try:
            result = await self.runner.run(scanner)
            ok = result.returncode in scanner.success_exit_codes
            raw = result.stdout if ok else _stderr_payload(result)
            await self.scanner_artifacts.store(
                scanner_run_id=scanner_run.id,
                kind=scanner.output_kind if ok else "text",
                content=raw,
            )

            if not ok:
                err = f"exit={result.returncode} stderr={result.stderr.decode('utf-8', 'replace')[:500]}"
                await self.scanner_runs.mark_failed(scanner_run.id, err)
                await self.session.commit()
                events.publish_scanner_completed(run_id, scanner.kind, "failed", 0, err)
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
            events.publish_scanner_completed(run_id, scanner.kind, "failed", 0, str(exc))
            return "failed"

    async def _run_project_tests(
        self,
        run_id: str,
        project_path: str,
    ) -> list[TestCaseRecord]:
        from pathlib import Path
        suites = discover_tests(Path(project_path))
        if not suites:
            return []

        events.publish_scanner_started(run_id, "project-tests")
        scanner_run = await self.scanner_runs.create(run_id, "project-tests")
        await self.scanner_runs.mark_running(scanner_run.id)
        await self.session.commit()

        try:
            all_cases: list[TestCaseRecord] = []
            combined_xml_parts: list[bytes] = []
            suite_failures = 0

            for suite in suites:
                result = await run_suite(suite, project_path=project_path)
                if not result.ok and result.returncode not in (0, 5):
                    suite_failures += 1
                    log.warning(
                        "test suite %s exited %d: %s",
                        suite.id, result.returncode,
                        result.stderr.decode("utf-8", "replace")[:200],
                    )
                if result.junit_xml:
                    combined_xml_parts.append(result.junit_xml)
                    cases = parse_junit(result.junit_xml, suite_id=suite.id)
                    for c in cases:
                        all_cases.append(TestCaseRecord(
                            qualified_name=c.qualified_name,
                            result=c.result,
                        ))

            if combined_xml_parts:
                combined = b"<testsuites>" + b"".join(combined_xml_parts) + b"</testsuites>"
                await self.scanner_artifacts.store(
                    scanner_run_id=scanner_run.id,
                    kind="junit-xml",
                    content=combined,
                )

            status = "completed" if suite_failures == 0 else "failed"
            if status == "failed":
                await self.scanner_runs.mark_failed(scanner_run.id, f"{suite_failures} suite(s) failed")
            else:
                await self.scanner_runs.mark_completed(scanner_run.id)
            await self.session.commit()
            events.publish_scanner_completed(run_id, "project-tests", status, len(all_cases))
            return all_cases

        except Exception as exc:
            await self.scanner_runs.mark_failed(scanner_run.id, str(exc))
            await self.session.commit()
            events.publish_scanner_completed(run_id, "project-tests", "failed", 0, str(exc))
            return []

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
            }
            for p in parsed
        ]
        await self.findings.bulk_insert(rows)

    async def _publish_findings(
        self,
        run_id: str,
        project_id: int,
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
            "project_id": project_id,
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
