"""FR-COMPLIANCE-AGGREGATE tests.

Verifies the compliance aggregation logic: given a set of FR states and a
mapping of compliance rows → FRs, the worst state across an FR set is
correctly derived per row. Also verifies the severity precedence ladder
(failed > pending > untested > blocked > waived > passed).
"""
from __future__ import annotations

from app.api.routes.compliance import _worst_state


# ---------------------------------------------------------------------------
# _worst_state — precedence ladder
# ---------------------------------------------------------------------------

def test_worst_state_returns_failed_if_any_failed() -> None:
    """Failed is the worst — even one failed FR in the set marks the row failed."""
    assert _worst_state(["failed", "passed", "untested"]) == "failed"
    assert _worst_state(["failed"]) == "failed"


def test_worst_state_returns_pending_if_no_failed_but_pending_present() -> None:
    """Pending beats untested/blocked/waived/passed in precedence."""
    assert _worst_state(["pending", "passed", "untested"]) == "pending"


def test_worst_state_returns_untested_when_only_untested_or_better() -> None:
    """Untested is worse than blocked/waived/passed."""
    assert _worst_state(["untested", "passed", "waived"]) == "untested"


def test_worst_state_returns_blocked_when_only_blocked_or_better() -> None:
    assert _worst_state(["blocked", "waived", "passed"]) == "blocked"


def test_worst_state_returns_waived_over_passed() -> None:
    """A waived row should still surface (not silently read as passed)."""
    assert _worst_state(["waived", "passed"]) == "waived"


def test_worst_state_all_passed_returns_passed() -> None:
    assert _worst_state(["passed", "passed", "passed"]) == "passed"


def test_worst_state_empty_returns_untested() -> None:
    """An unmapped row (no FRs) reads as untested, not as a degenerate pass."""
    assert _worst_state([]) == "untested"


def test_worst_state_unrecognized_states_are_ignored() -> None:
    """Unknown states don't crash and don't contaminate the precedence lookup —
    only known states participate in the worst-state decision.
    """
    # Unknown mixed with passed: worst known is passed.
    assert _worst_state(["unknown-state", "passed"]) == "passed"
    # Only unknown states: nothing recognised, falls through to the untested default.
    assert _worst_state(["bogus"]) == "untested"


# ---------------------------------------------------------------------------
# Aggregation scenarios that exercise the precedence ladder end-to-end
# ---------------------------------------------------------------------------

def test_failed_dominates_even_with_many_passing_frs() -> None:
    """If 9 of 10 FRs pass but 1 fails, the compliance row is failed —
    compliance is a worst-state measure, not an average.
    """
    states = ["passed"] * 9 + ["failed"]
    assert _worst_state(states) == "failed"


def test_waived_does_not_mask_failed() -> None:
    """A waiver on one FR doesn't suppress a failed state on another FR
    mapped to the same compliance row.
    """
    assert _worst_state(["waived", "failed"]) == "failed"
