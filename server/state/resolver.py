"""v3 state resolver.

Per-FR state is computed from test evaluations + waivers + dependencies.
The precedence ladder is simpler than v2 — no more evidence-mixing:

  waived
  blocked        (any dep not in {passed, waived})
  failed         (at least one test result = fail)
  passed         (all tests pass)
  pending        (tests defined, none evaluated yet)
  untested       (no tests defined on the FR)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.state.matcher import TestEvaluation


FR_STATES: tuple[str, ...] = (
    "untested",
    "pending",
    "passed",
    "failed",
    "waived",
    "blocked",
)

# States treated as gaps by the gap-analysis tool.
GAP_STATES: tuple[str, ...] = (
    "untested",
    "pending",
    "failed",
    "blocked",
)


@dataclass
class StateResult:
    """Computed state for one FR."""

    state: str
    reason: dict[str, Any] = field(default_factory=dict)


def evaluate_fr(
    fr: dict[str, Any],
    test_evaluations: dict[str, TestEvaluation],   # {test_id: evaluation}
    waivers_present: bool,
    dep_states: dict[str, str],                    # {dep_fr_id: state}
) -> StateResult:
    """Compute the state of one FR using the precedence ladder."""

    if waivers_present:
        return StateResult("waived", {"source": "standing_waiver"})

    blocking_deps = {
        dep: state
        for dep, state in dep_states.items()
        if state not in ("passed", "waived")
    }
    if blocking_deps:
        return StateResult("blocked", {"blocking_deps": blocking_deps})

    tests = fr.get("tests", []) or []
    if not tests:
        return StateResult("untested", {"note": "no tests defined"})

    if not test_evaluations:
        return StateResult("pending", {"note": "tests defined, none evaluated yet"})

    failures = [
        {"test_id": tid, "detail": ev.detail}
        for tid, ev in test_evaluations.items()
        if ev.result == "fail"
    ]
    if failures:
        return StateResult("failed", {"failures": failures})

    # All evaluations are pass or pending. If any pending, the FR isn't done.
    pending = [
        {"test_id": tid, "detail": ev.detail}
        for tid, ev in test_evaluations.items()
        if ev.result == "pending"
    ]
    if pending:
        return StateResult(
            "pending",
            {"note": "some tests have not produced results yet", "pending": pending},
        )

    return StateResult(
        "passed",
        {
            "test_count": len(test_evaluations),
            "tests": list(test_evaluations.keys()),
        },
    )
