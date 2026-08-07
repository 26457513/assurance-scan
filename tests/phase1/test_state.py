"""FR state resolver tests. Each test pins one precedence-rung transition."""
from __future__ import annotations

from server.state.matcher import EvidenceRecord
from server.state.resolver import compute_fr_state


def _fr(**overrides) -> dict:
    base = {
        "id": "FR-1",
        "title": "T",
        "description": "D",
        "required_evidence": {},
        "satisfies": [],
        "depends_on": [],
    }
    base.update(overrides)
    return base


def test_untested_when_no_required_and_no_evidence() -> None:
    result = compute_fr_state(_fr(), [], waivers_present=False, dep_states={})
    assert result.state == "untested"


def test_to_be_tested_when_required_defined_but_no_evidence() -> None:
    fr = _fr(required_evidence={"all_of": [{"type": "scanner-result", "source_kind": "semgrep", "rule_id": "X"}]})
    result = compute_fr_state(fr, [], waivers_present=False, dep_states={})
    assert result.state == "to-be-tested"


def test_waived_takes_precedence_over_everything() -> None:
    fr = _fr(required_evidence={"none_of": [{"type": "scanner-result", "source_kind": "s", "rule_id": "x"}]})
    ev = EvidenceRecord(type="scanner-result", source={"kind": "s", "rule_id": "x"}, result="fail")
    result = compute_fr_state(fr, [ev], waivers_present=True, dep_states={})
    assert result.state == "waived"


def test_blocked_when_a_dep_is_not_passed() -> None:
    fr = _fr(depends_on=["FR-OTHER"])
    result = compute_fr_state(fr, [], waivers_present=False, dep_states={"FR-OTHER": "to-be-tested"})
    assert result.state == "blocked"


def test_blocked_bypassed_when_dep_is_passed() -> None:
    fr = _fr(
        depends_on=["FR-OTHER"],
        required_evidence={"all_of": [{"type": "scanner-result", "source_kind": "s", "rule_id": "x", "expected_result": "pass"}]},
    )
    ev = EvidenceRecord(type="scanner-result", source={"kind": "s", "rule_id": "x"}, result="pass")
    result = compute_fr_state(fr, [ev], waivers_present=False, dep_states={"FR-OTHER": "passed"})
    assert result.state == "passed"


def test_manual_review_when_same_spec_has_pass_and_fail() -> None:
    spec = {"type": "scanner-result", "source_kind": "s", "rule_id": "x", "expected_result": "pass"}
    fr = _fr(required_evidence={"all_of": [spec]})
    ev_pass = EvidenceRecord(type="scanner-result", source={"kind": "s", "rule_id": "x"}, result="pass")
    ev_fail = EvidenceRecord(type="scanner-result", source={"kind": "s", "rule_id": "x"}, result="fail")
    result = compute_fr_state(fr, [ev_pass, ev_fail], waivers_present=False, dep_states={})
    assert result.state == "manual-review"


def test_failed_when_none_of_violated() -> None:
    fr = _fr(required_evidence={"none_of": [{"type": "scanner-result", "source_kind": "s", "rule_id": "bad"}]})
    ev = EvidenceRecord(type="scanner-result", source={"kind": "s", "rule_id": "bad"}, result="fail")
    result = compute_fr_state(fr, [ev], waivers_present=False, dep_states={})
    assert result.state == "failed"


def test_passed_when_all_of_and_any_of_satisfied() -> None:
    fr = _fr(required_evidence={
        "all_of": [{"type": "scanner-result", "source_kind": "s", "rule_id": "a", "expected_result": "pass"}],
        "any_of": [
            {"type": "scanner-result", "source_kind": "s", "rule_id": "b", "expected_result": "pass"},
            {"type": "scanner-result", "source_kind": "s", "rule_id": "c", "expected_result": "pass"},
        ],
    })
    # Evidence for all_of (rule "a") and one any_of option (rule "c").
    evs = [
        EvidenceRecord(type="scanner-result", source={"kind": "s", "rule_id": "a"}, result="pass"),
        EvidenceRecord(type="scanner-result", source={"kind": "s", "rule_id": "c"}, result="pass"),
    ]
    result = compute_fr_state(fr, evs, waivers_present=False, dep_states={})
    assert result.state == "passed"


def test_failed_when_all_of_not_satisfied() -> None:
    fr = _fr(required_evidence={
        "all_of": [{"type": "scanner-result", "source_kind": "s", "rule_id": "a", "expected_result": "pass"}],
    })
    # Has evidence for a different rule.
    ev = EvidenceRecord(type="scanner-result", source={"kind": "s", "rule_id": "other"}, result="pass")
    result = compute_fr_state(fr, [ev], waivers_present=False, dep_states={})
    assert result.state == "failed"


def test_has_evidence_when_required_empty_but_evidence_present() -> None:
    fr = _fr()  # no required_evidence
    ev = EvidenceRecord(type="manual-attestation", source={}, result="manual")
    result = compute_fr_state(fr, [ev], waivers_present=False, dep_states={})
    assert result.state == "has-evidence"
