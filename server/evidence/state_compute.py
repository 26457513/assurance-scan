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

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.catalogue.loader import LoadedCatalogue
from server.db.models import Finding
from server.db.repositories.fr_state import FrStateRepository
from server.db.repositories.frs import FrRepository
from server.db.repositories.test_results import TestResultRepository
from server.db.repositories.waivers import WaiverRepository
from server.state.matcher import (
    FindingRecord,
    TestCaseRecord,
    evaluate_test,
)
from server.state.resolver import evaluate_fr


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

                # Evaluate each test on this FR.
                evaluations: dict[str, object] = {}
                for test in tests:
                    test_id = test.get("id", "")
                    if not test_id:
                        continue
                    evaluation = evaluate_test(
                        spec=test,
                        findings=finding_records,
                        test_cases=test_cases,
                    )
                    evaluations[test_id] = evaluation
                    await test_results_repo.upsert(
                        run_id=run_id,
                        project_path=project_path,
                        fr_id=fr.fr_id,
                        test_id=test_id,
                        test_type=test.get("type", "unknown"),
                        result=evaluation.result,
                        detail=evaluation.detail,
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
    digest = hashlib.sha1(
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
