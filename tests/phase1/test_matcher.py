"""Evidence-to-spec matcher tests."""
from __future__ import annotations

from server.state.matcher import EvidenceRecord, matches_spec, spec_matches_count


def _evidence(type_: str, result: str = "pass", **source) -> EvidenceRecord:
    """Evidence record helper. `source` keys match the on-disk schema (`kind`,
    `rule_id`, `test_name`, `format`), not the catalogue spec field names
    (`source_kind`, `name_pattern`)."""
    return EvidenceRecord(type=type_, source=source, result=result)


def test_scanner_result_matches_on_kind_and_rule() -> None:
    spec = {"type": "scanner-result", "source_kind": "semgrep", "rule_id": "X"}
    ev = _evidence("scanner-result", kind="semgrep", rule_id="X")
    assert matches_spec(spec, ev)

    wrong_kind = _evidence("scanner-result", kind="trivy-fs", rule_id="X")
    assert not matches_spec(spec, wrong_kind)

    wrong_rule = _evidence("scanner-result", kind="semgrep", rule_id="Y")
    assert not matches_spec(spec, wrong_rule)


def test_unit_test_matches_via_glob_pattern() -> None:
    spec = {"type": "unit-test", "name_pattern": "tests/auth/test_session.py::*"}
    assert matches_spec(spec, _evidence("unit-test", test_name="tests/auth/test_session.py::TestSession::test_timeout"))
    assert matches_spec(spec, _evidence("unit-test", test_name="tests/auth/test_session.py::test_simple"))
    assert not matches_spec(spec, _evidence("unit-test", test_name="tests/other/test.py::test_x"))


def test_manual_attestation_matches_on_type_only() -> None:
    spec = {"type": "manual-attestation"}
    assert matches_spec(spec, _evidence("manual-attestation"))


def test_imported_matches_on_format() -> None:
    spec = {"type": "imported", "format": "junit-xml"}
    assert matches_spec(spec, _evidence("imported", format="junit-xml"))
    assert not matches_spec(spec, _evidence("imported", format="sarif"))


def test_type_mismatch_short_circuits() -> None:
    spec = {"type": "scanner-result", "source_kind": "semgrep"}
    assert not matches_spec(spec, _evidence("unit-test"))


def test_spec_matches_count_detects_satisfaction_and_conflict() -> None:
    spec = {"type": "scanner-result", "source_kind": "semgrep", "rule_id": "X", "expected_result": "pass"}

    # Pass-only → satisfied, no conflict.
    (_, has_fail), satisfied = spec_matches_count(
        spec, [_evidence("scanner-result", "pass", kind="semgrep", rule_id="X")]
    )
    assert satisfied
    assert not has_fail

    # Fail-only → not satisfied, conflict.
    (_, has_fail), satisfied = spec_matches_count(
        spec, [_evidence("scanner-result", "fail", kind="semgrep", rule_id="X")]
    )
    assert not satisfied
    assert has_fail

    # Both pass and fail → satisfied AND conflicted.
    (_, has_fail), satisfied = spec_matches_count(
        spec, [
            _evidence("scanner-result", "pass", kind="semgrep", rule_id="X"),
            _evidence("scanner-result", "fail", kind="semgrep", rule_id="X"),
        ]
    )
    assert satisfied
    assert has_fail
