"""v3 state machine.

Each FR has a list of `tests`. After a scan, each test is evaluated to
pass / fail / pending. The FR's state is computed from the test results
plus standing waivers and FR dependencies.

Public surface:
  - `evaluate_fr(fr, test_results, waivers_present, dep_states)` -> StateResult
  - `evaluate_test(spec, findings, test_case_results)` -> TestEvaluation
  - `FR_STATES`, `GAP_STATES`
"""
from app.state.matcher import (
    TestEvaluation,
    evaluate_test,
)
from app.state.resolver import (
    FR_STATES,
    GAP_STATES,
    StateResult,
    evaluate_fr,
)

__all__ = [
    "FR_STATES",
    "GAP_STATES",
    "StateResult",
    "TestEvaluation",
    "evaluate_fr",
    "evaluate_test",
]
