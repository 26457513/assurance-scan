"""Compute and cache FR states for a run.

Reads: catalogue snapshot for the run, evidence for the run, waivers for
the project, depends_on relationships. Writes: fr_state rows (cached).
Transitive dep states are resolved via topological order; cycles would
have been rejected at catalogue-load time.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from server.catalogue.loader import LoadedCatalogue
from server.db.repositories.evidence import EvidenceRepository
from server.db.repositories.fr_state import FrStateRepository
from server.db.repositories.frs import FrRepository
from server.db.repositories.waivers import WaiverRepository
from server.state.matcher import EvidenceRecord
from server.state.resolver import compute_fr_state


log = logging.getLogger(__name__)


async def compute_states_for_run(
    session: AsyncSession,
    run_id: str,
    project_path: str,
    catalogue: LoadedCatalogue,
) -> dict[str, str]:
    """Compute the state of every FR in the catalogue snapshot for this run.

    Returns a dict mapping fr_id -> state for transitive-depend resolution
    by callers.
    """
    frs_repo = FrRepository(session)
    evidence_repo = EvidenceRepository(session)
    state_repo = FrStateRepository(session)
    waivers_repo = WaiverRepository(session)

    # Clear any previously-computed state for this run (idempotent recompute).
    await state_repo.delete_for_run(run_id)

    snapshot_id = catalogue.content_hash
    fr_rows = await frs_repo.list_for_snapshot(_snapshot_id_for(catalogue))
    if not fr_rows:
        log.warning(
            "no FRs in catalogue snapshot %s; did the snapshot get loaded?",
            snapshot_id,
        )
        return {}

    # Pre-fetch evidence and waivers, keyed by fr_id for fast lookup.
    all_evidence = await evidence_repo.list_for_run(run_id)
    evidence_by_fr: dict[str, list[EvidenceRecord]] = {}
    for ev in all_evidence:
        rec = EvidenceRecord(
            type=ev.type,
            source=json.loads(ev.source_json or "{}"),
            result=ev.result,
        )
        evidence_by_fr.setdefault(ev.fr_id, []).append(rec)

    all_waivers = await waivers_repo.list_for_project(project_path)
    waiver_frs: set[str] = {w.fr_id for w in all_waivers}

    # Topological-ish order: compute leaf FRs first, then dependents.
    # Since cycles are rejected at load time, two passes suffice.
    states_by_id: dict[str, str] = {fr.fr_id: "untested" for fr in fr_rows}
    fr_dicts_by_id: dict[str, dict[str, Any]] = {
        fr.fr_id: _fr_row_to_dict(fr) for fr in fr_rows
    }

    # Pass 1: compute FRs with no depends_on (leaves).
    # Pass 2: compute FRs that depend on already-computed FRs.
    # Repeat until stable.
    pending = list(fr_rows)
    progress = True
    while pending and progress:
        progress = False
        next_pending = []
        for fr in pending:
            deps = json.loads(fr.depends_on_json or "[]")
            if all(d in states_by_id and states_by_id[d] != "untested" or d not in fr_dicts_by_id for d in deps):
                # All deps computed (or external — treat as passed).
                dep_states = {
                    d: states_by_id.get(d, "passed")
                    for d in deps
                }
                state = compute_fr_state(
                    fr=fr_dicts_by_id[fr.fr_id],
                    evidence_records=evidence_by_fr.get(fr.fr_id, []),
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

    # Any remaining pending FRs have dep cycles that slipped past load-time
    # validation. Mark them blocked as a safety net.
    for fr in pending:
        await state_repo.upsert(
            project_path=project_path,
            fr_id=fr.fr_id,
            run_id=run_id,
            state="blocked",
            reason={"error": "dep_cycle_or_unresolved"},
        )
        states_by_id[fr.fr_id] = "blocked"

    log.info(
        "computed %d FR states for run %s",
        len(states_by_id),
        run_id,
    )
    return states_by_id


def _snapshot_id_for(catalogue: LoadedCatalogue) -> str:
    """Reconstruct the snapshot id used by CatalogueSnapshotRepository."""
    import hashlib
    digest = hashlib.sha1(
        f"{catalogue.project_path}|{catalogue.content_hash}".encode()
    ).hexdigest()[:16]
    return f"snap_{digest}"


def _fr_row_to_dict(row) -> dict[str, Any]:
    """Convert a Fr ORM row into the dict shape compute_fr_state expects."""
    return {
        "id": row.fr_id,
        "title": row.title,
        "description": row.description,
        "implemented_by": json.loads(row.implemented_by_json or "[]"),
        "required_evidence": json.loads(row.required_evidence_json or "{}"),
        "satisfies": json.loads(row.satisfies_json or "[]"),
        "depends_on": json.loads(row.depends_on_json or "[]"),
    }
