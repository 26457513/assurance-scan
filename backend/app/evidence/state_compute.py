"""v3 state computation: evaluate each test on each FR.

Replaces the v2 model of (collect evidence + synthesize negative evidence +
match against required_evidence). The v3 model is:
  - For each FR in the catalogue
  - For each test on that FR
  - Evaluate the test using its type-specific evaluator
  - Store the TestResult
  - Compute FR state from the set of TestResults + waivers + deps
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalogue.loader import LoadedCatalogue
from app.infrastructure.db.models import Finding, FindingAcceptance, ScannerRun
from app.infrastructure.db.repositories.fr_state import FrStateRepository
from app.infrastructure.db.repositories.frs import FrRepository
from app.infrastructure.db.repositories.test_results import TestResultRepository
from app.infrastructure.db.repositories.waivers import WaiverRepository
from app.state.matcher import (
    FindingRecord,
    TestCaseRecord,
    TestEvaluation,
    evaluate_test,
)
from app.state.resolver import evaluate_fr


log = logging.getLogger(__name__)


async def evaluate_tests_and_compute_states(
    session: AsyncSession,
    run_id: str,
    project_path: str,
    catalogue: LoadedCatalogue,
    test_cases: list[TestCaseRecord],
) -> dict[str, str]:
    """Top-level entrypoint called by the orchestrator after scans complete.

    Returns a dict {fr_id: state} for dependency resolution by callers.
    """
    frs_repo = FrRepository(session)
    state_repo = FrStateRepository(session)
    waivers_repo = WaiverRepository(session)
    test_results_repo = TestResultRepository(session)

    # Clear any previously-computed state for this run (idempotent recompute).
    await state_repo.delete_for_run(run_id)

    snapshot_id = _snapshot_id_for(catalogue)
    fr_rows = await frs_repo.list_for_snapshot(snapshot_id)
    if not fr_rows:
        log.warning(
            "no FRs in catalogue snapshot %s; did the snapshot get loaded?",
            snapshot_id,
        )
        return {}

    # Pre-fetch findings (full list for the run, converted to records once).
    finding_rows = (await session.execute(
        select(Finding).where(Finding.run_id == run_id)
    )).scalars().all()
    finding_records: list[FindingRecord] = [
        FindingRecord(
            scanner_kind=f.scanner_kind,
            rule_id=f.rule_id,
            severity=f.severity,
            file_path=f.file_path,
        )
        for f in finding_rows
    ]

    # Pre-fetch waivers.
    all_waivers = await waivers_repo.list_for_project(project_path)
    waiver_frs: set[str] = {w.fr_id for w in all_waivers}

    # Pre-fetch finding acceptances (per-finding risk triage).
    now = _dt.datetime.now(_dt.timezone.utc)
    acceptance_rows = (await session.execute(
        select(FindingAcceptance).where(FindingAcceptance.project_path == project_path)
    )).scalars().all()
    accepted_keys: set[tuple[str, str]] = set()
    for acc in acceptance_rows:
        if acc.expires_at is None or acc.expires_at > now:
            accepted_keys.add((acc.scanner_kind, acc.rule_id))

    # Partition findings: separate accepted from actionable.
    # Matching uses prefix comparison because osv-scanner rule_ids include CVE
    # aliases in parentheses (e.g. "GHSA-xxx (CVE-yyy, PYSEC-zzz)") while
    # acceptance records may store just the primary GHSA ID.
    filtered_records: list[FindingRecord] = []
    accepted_by_scanner: dict[str, int] = {}
    for f in finding_records:
        f_scanner = f.scanner_kind
        f_rule = f.rule_id or ""
        is_accepted = (f_scanner, f_rule) in accepted_keys
        if not is_accepted and f_rule:
            # Fuzzy: check if any accepted (scanner, rule_id) is a prefix of the
            # finding's rule_id (handles the "(CVE-..." suffix from osv-scanner).
            for acc_scanner, acc_rule in accepted_keys:
                if acc_scanner == f_scanner and f_rule.startswith(acc_rule):
                    is_accepted = True
                    break
        if is_accepted:
            accepted_by_scanner[f_scanner] = accepted_by_scanner.get(f_scanner, 0) + 1
        else:
            filtered_records.append(f)

    # Load scanner run statuses — needed to distinguish "scanner ran and found
    # nothing" (pass) from "scanner didn't run" (pending).
    scanner_run_rows = (await session.execute(
        select(ScannerRun).where(ScannerRun.run_id == run_id)
    )).scalars().all()
    scanners_that_ran: set[str] = {
        sr.scanner_kind for sr in scanner_run_rows if sr.status == "completed"
    }

    # Parse FR JSON columns once.
    fr_dicts_by_id: dict[str, dict[str, Any]] = {
        fr.fr_id: {
            "id": fr.fr_id,
            "tests": json.loads(fr.required_evidence_json or "[]")  # see note below
                if False else
                _load_tests_from_catalogue(catalogue, fr.fr_id),
            "depends_on": json.loads(fr.depends_on_json or "[]"),
        }
        for fr in fr_rows
    }

    # Evaluate tests per FR.
    states_by_id: dict[str, str] = {fr.fr_id: "untested" for fr in fr_rows}

    # Topological-ish: leaf FRs first.
    pending = list(fr_rows)
    progress = True
    while pending and progress:
        progress = False
        next_pending = []
        for fr in pending:
            deps = json.loads(fr.depends_on_json or "[]")
            if all(d in states_by_id or d not in fr_dicts_by_id for d in deps):
                fr_dict = fr_dicts_by_id[fr.fr_id]
                tests = fr_dict["tests"]

                # Evaluate each test on this FR (with accepted findings filtered out).
                evaluations: dict[str, TestEvaluation] = {}
                for test in tests:
                    test_id = test.get("id", "")
                    if not test_id:
                        continue
                    evaluation = evaluate_test(
                        spec=test,
                        findings=filtered_records,
                        test_cases=test_cases,
                    )
                    evaluations[test_id] = evaluation

                # Post-process: scanner-clean tests where the scanner ran but
                # produced zero findings → pass (not pending). The matcher
                # returns "pending" when no findings exist because it can't
                # tell whether the scanner ran. We know from scanner_status.
                for test in tests:
                    test_id = test.get("id", "")
                    if test_id not in evaluations:
                        continue
                    ev = evaluations[test_id]
                    if ev.result == "pending":
                        scanner = test.get("scanner", "")
                        note = ev.detail.get("note", "")
                        if scanner in scanners_that_ran and "produced no findings" in note:
                            evaluations[test_id] = TestEvaluation(
                                result="pass",
                                detail={"scanner": scanner, "total_findings": 0,
                                        "note": "scanner ran with zero matching findings"},
                            )

                # Post-process: scanner-clean tests that passed but had accepted
                # findings → mark as "accepted" (distinct from clean "pass").
                for test in tests:
                    test_id = test.get("id", "")
                    if test_id not in evaluations:
                        continue
                    ev = evaluations[test_id]
                    if ev.result == "pass" and test.get("type", "").startswith("scanner-clean"):
                        scanner = test.get("scanner", "")
                        accepted_n = accepted_by_scanner.get(scanner, 0)
                        if accepted_n > 0:
                            evaluations[test_id] = TestEvaluation(
                                result="accepted",
                                detail={**ev.detail, "accepted_count": accepted_n}
                            )

                # Store all test results (after post-processing).
                for test in tests:
                    test_id = test.get("id", "")
                    if test_id not in evaluations:
                        continue
                    ev = evaluations[test_id]
                    await test_results_repo.upsert(
                        run_id=run_id,
                        project_path=project_path,
                        fr_id=fr.fr_id,
                        test_id=test_id,
                        test_type=test.get("type", "unknown"),
                        result=ev.result,
                        detail=ev.detail,
                    )

                dep_states = {d: states_by_id.get(d, "passed") for d in deps}
                state = evaluate_fr(
                    fr=fr_dict,
                    test_evaluations=evaluations,
                    waivers_present=fr.fr_id in waiver_frs,
                    dep_states=dep_states,
                )
                states_by_id[fr.fr_id] = state.state
                await state_repo.upsert(
                    project_path=project_path,
                    fr_id=fr.fr_id,
                    run_id=run_id,
                    state=state.state,
                    reason=state.reason,
                )
                progress = True
            else:
                next_pending.append(fr)
        pending = next_pending

    # Cycle safety net.
    for fr in pending:
        await state_repo.upsert(
            project_path=project_path,
            fr_id=fr.fr_id,
            run_id=run_id,
            state="blocked",
            reason={"error": "dep_cycle_or_unresolved"},
        )
        states_by_id[fr.fr_id] = "blocked"

    log.info("computed %d FR states for run %s", len(states_by_id), run_id)
    return states_by_id


def _snapshot_id_for(catalogue: LoadedCatalogue) -> str:
    import hashlib

    # Must match the persisted snapshot identity algorithm. SHA-1 is used only
    # as a stable compact identifier here, never for authentication or integrity.
    digest = hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
        f"{catalogue.project_path}|{catalogue.content_hash}".encode()
    ).hexdigest()[:16]
    return f"snap_{digest}"


def _load_tests_from_catalogue(
    catalogue: LoadedCatalogue,
    fr_id: str,
) -> list[dict[str, Any]]:
    """Pull the tests array for an FR from the in-memory catalogue doc.

    The DB doesn't store tests separately — only the catalogue snapshot
    does. Looking them up by FR id is O(FRs) per scan, which is fine.
    """
    for fr in catalogue.doc.get("frs", []):
        if fr.get("id") == fr_id:
            return fr.get("tests", []) or []
    return []
