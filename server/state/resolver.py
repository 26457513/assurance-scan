"""8-state resolver with the precedence ladder.

States are evaluated top-down; first match wins:

  waived
  blocked
  manual-review
  failed
  passed
  has-evidence
  to-be-tested
  untested

Inputs:
  - `fr` dict from the catalogue snapshot
  - `evidence_records` list of EvidenceRecord for this FR
  - `waivers_present` bool: at least one unexpired waiver applies
  - `dep_states` dict[fr_id -> state] for direct `depends_on` deps
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.state.matcher import (
    EvidenceRecord,
    spec_matches_count,
)


FR_STATES: tuple[str, ...] = (
    "untested",
    "to-be-tested",
    "has-evidence",
    "passed",
    "failed",
    "manual-review",
    "waived",
    "blocked",
)

# States treated as gaps by the gap-analysis tool.
GAP_STATES: tuple[str, ...] = (
    "untested",
    "to-be-tested",
    "failed",
    "manual-review",
    "blocked",
)


@dataclass
class StateResult:
    """Computed state for one FR."""

    state: str
    reason: dict[str, Any] = field(default_factory=dict)


def compute_fr_state(
    fr: dict[str, Any],
    evidence_records: list[EvidenceRecord],
    waivers_present: bool,
    dep_states: dict[str, str],
) -> StateResult:
    """Compute the state of one FR using the precedence ladder."""

    # 1. waived — highest precedence
    if waivers_present:
        return StateResult("waived", {"source": "standing_waiver"})

    # 2. blocked — depends on a non-{passed, waived} FR
    deps = fr.get("depends_on", []) or []
    blocking_deps = {
        dep: state
        for dep, state in dep_states.items()
        if state not in ("passed", "waived")
    }
    if blocking_deps:
        return StateResult(
            "blocked",
            {"blocking_deps": blocking_deps},
        )

    required = fr.get("required_evidence", {}) or {}
    all_of = required.get("all_of", []) or []
    any_of = required.get("any_of", []) or []
    none_of = required.get("none_of", []) or []

    # Pre-compute spec results
    any_evidence = bool(evidence_records)
    has_required = bool(all_of or any_of or none_of)

    if not any_evidence:
        if has_required:
            return StateResult("to-be-tested", {"required_evidence_defined": True})
        return StateResult("untested", {"required_evidence_defined": False})

    # 3. manual-review — any spec is conflicted (pass and fail both present)
    conflict_specs = _conflicted_specs(all_of, any_of, evidence_records)
    if conflict_specs:
        return StateResult(
            "manual-review",
            {"conflict_specs": conflict_specs},
        )

    # 4/5/6. failed / passed / has-evidence
    if not has_required:
        return StateResult(
            "has-evidence",
            {"note": "no required_evidence defined"},
        )

    none_of_violated = _none_of_violated(none_of, evidence_records)
    all_of_ok = all(
        _spec_satisfied(spec, evidence_records) for spec in all_of
    )
    any_of_ok = (
        any(_spec_satisfied(spec, evidence_records) for spec in any_of)
        if any_of
        else True
    )

    if none_of_violated or not all_of_ok or not any_of_ok:
        # If sufficient evidence is present but not satisfied, it's a fail.
        return StateResult(
            "failed",
            {
                "all_of_satisfied": all_of_ok,
                "any_of_satisfied": any_of_ok,
                "none_of_clean": not none_of_violated,
            },
        )

    return StateResult(
        "passed",
        {
            "all_of_satisfied": all_of_ok,
            "any_of_satisfied": any_of_ok,
            "evidence_count": len(evidence_records),
        },
    )


def _spec_satisfied(
    spec: dict[str, Any],
    evidence_records: list[EvidenceRecord],
) -> bool:
    """True if any evidence record matches the spec with expected_result."""
    (_, _), satisfied = spec_matches_count(spec, evidence_records)
    return satisfied


def _none_of_violated(
    none_of: list[dict[str, Any]],
    evidence_records: list[EvidenceRecord],
) -> bool:
    """True if any evidence matches a `none_of` spec (negative evidence)."""
    from server.state.matcher import matches_spec
    for spec in none_of:
        if any(matches_spec(spec, e) for e in evidence_records):
            return True
    return False


def _conflicted_specs(
    all_of: list[dict[str, Any]],
    any_of: list[dict[str, Any]],
    evidence_records: list[EvidenceRecord],
) -> list[dict[str, Any]]:
    """Return specs that have both pass and fail evidence (true conflict)."""
    conflicts: list[dict[str, Any]] = []
    for spec in [*all_of, *any_of]:
        (_, has_fail), satisfied = spec_matches_count(spec, evidence_records)
        if has_fail and satisfied:
            conflicts.append(spec)
    return conflicts
