"""v3 state resolver tests."""
from __future__ import annotations

from app.state.matcher import TestEvaluation
from app.state.resolver import evaluate_fr


def _fr(**overrides) -> dict:
    base = {
        "id": "FR-1",
        "tests": [{"id": "t1", "type": "scanner-clean", "scanner": "x"}],
        "depends_on": [],
    }
    base.update(overrides)
    return base


def test_untested_when_no_tests_defined() -> None:
    fr = _fr(tests=[])
    result = evaluate_fr(fr, {}, waivers_present=False, dep_states={})
    assert result.state == "untested"


def test_pending_when_tests_defined_but_none_evaluated() -> None:
    result = evaluate_fr(_fr(), {}, waivers_present=False, dep_states={})
    assert result.state == "pending"


def test_passed_when_all_tests_pass() -> None:
    evals = {"t1": TestEvaluation("pass")}
    result = evaluate_fr(_fr(), evals, waivers_present=False, dep_states={})
    assert result.state == "passed"


def test_failed_when_any_test_fails() -> None:
    evals = {
        "t1": TestEvaluation("pass"),
        "t2": TestEvaluation("fail", {"why": "scanner found X"}),
    }
    fr = _fr(tests=[
        {"id": "t1", "type": "scanner-clean", "scanner": "x"},
        {"id": "t2", "type": "scanner-clean", "scanner": "y"},
    ])
    result = evaluate_fr(fr, evals, waivers_present=False, dep_states={})
    assert result.state == "failed"


def test_pending_when_some_pass_some_pending() -> None:
    evals = {
        "t1": TestEvaluation("pass"),
        "t2": TestEvaluation("pending"),
    }
    fr = _fr(tests=[
        {"id": "t1", "type": "scanner-clean", "scanner": "x"},
        {"id": "t2", "type": "scanner-clean", "scanner": "y"},
    ])
    result = evaluate_fr(fr, evals, waivers_present=False, dep_states={})
    assert result.state == "pending"


def test_waived_overrides_everything() -> None:
    evals = {"t1": TestEvaluation("fail")}
    result = evaluate_fr(_fr(), evals, waivers_present=True, dep_states={})
    assert result.state == "waived"


def test_blocked_when_a_dep_is_not_passed() -> None:
    result = evaluate_fr(
        _fr(depends_on=["FR-OTHER"]),
        {},
        waivers_present=False,
        dep_states={"FR-OTHER": "pending"},
    )
    assert result.state == "blocked"


def test_blocked_bypassed_when_dep_passed() -> None:
    evals = {"t1": TestEvaluation("pass")}
    result = evaluate_fr(
        _fr(depends_on=["FR-OTHER"]),
        evals,
        waivers_present=False,
        dep_states={"FR-OTHER": "passed"},
    )
    assert result.state == "passed"


def test_failed_overrides_pending_when_mixed() -> None:
    """If a test failed, the FR is failed even if others are pending."""
    evals = {
        "t1": TestEvaluation("fail"),
        "t2": TestEvaluation("pending"),
    }
    fr = _fr(tests=[
        {"id": "t1", "type": "scanner-clean", "scanner": "x"},
        {"id": "t2", "type": "scanner-clean", "scanner": "y"},
    ])
    result = evaluate_fr(fr, evals, waivers_present=False, dep_states={})
    assert result.state == "failed"
