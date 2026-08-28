"""v3 evidence/state-computation layer.

The v2 concepts of `collect_evidence_from_findings` and
`synthesize_negative_evidence` are gone — tests are now declared inline
on each FR and evaluated directly.
"""
from app.evidence.state_compute import evaluate_tests_and_compute_states

__all__ = ["evaluate_tests_and_compute_states"]
