"""FR state resolution.

Public surface:
  - `compute_fr_state(fr, evidence, waivers, dep_states)` -> StateResult
  - `FR_STATES` tuple of valid states
  - `GAP_STATES` states the gap analysis considers "needs work"
"""
from server.state.matcher import matches_spec, ConflictError
from server.state.resolver import (
    FR_STATES,
    GAP_STATES,
    StateResult,
    compute_fr_state,
)

__all__ = [
    "FR_STATES",
    "GAP_STATES",
    "StateResult",
    "compute_fr_state",
    "matches_spec",
    "ConflictError",
]
