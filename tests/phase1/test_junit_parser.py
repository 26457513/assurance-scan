"""FR-TEST-DISCOVER tests.

Verifies the JUnit XML parser that turns project-test output into per-testcase
records. JUnit XML is the de-facto interchange format (pytest, jest-junit,
gradle, maven surefire all emit it). Each testcase becomes one record keyed
by `<classname>::<name>` — the format the matcher uses to bind tests to FRs.

Also covers XXE resistance: the parser uses defusedxml so external entities
in malicious JUnit input cannot exfiltrate data or cause DoS.
"""
from __future__ import annotations

from server.worker.parsers.junit import parse


def _xml(body: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
{body}
""".encode()


def test_parse_empty_input_returns_empty_list() -> None:
    """Empty input (no JUnit emitted, e.g. tests crashed before output) is graceful."""
    assert parse(b"", suite_id="s") == []


def test_parse_invalid_xml_returns_empty_list() -> None:
    """Malformed XML doesn't crash — returns empty so the scan continues."""
    assert parse(b"<not valid xml", suite_id="s") == []


def test_parse_passing_testcase_marked_as_pass() -> None:
    """A testcase with no failure/error/skipped child is a pass."""
    xml = _xml("""<testsuite name="s">
      <testcase name="test_ok" classname="tests.test_mod" time="0.01"/>
    </testsuite>""")
    results = parse(xml, suite_id="suite-1")
    assert len(results) == 1
    r = results[0]
    assert r.name == "test_ok"
    assert r.classname == "tests.test_mod"
    assert r.qualified_name == "tests.test_mod::test_ok"
    assert r.result == "pass"
    assert r.elapsed_seconds == 0.01


def test_parse_failure_element_marks_testcase_failed() -> None:
    xml = _xml("""<testsuite name="s">
      <testcase name="test_bad" classname="tests.test_mod">
        <failure message="assert false">Traceback...</failure>
      </testcase>
    </testsuite>""")
    results = parse(xml, suite_id="s")
    assert results[0].result == "fail"
    assert results[0].failure_message == "assert false"


def test_parse_error_element_marks_testcase_errored() -> None:
    """An <error> child (e.g. uncaught exception) is distinct from <failure>."""
    xml = _xml("""<testsuite name="s">
      <testcase name="test_boom" classname="t">
        <error message="ZeroDivisionError">/ by zero</error>
      </testcase>
    </testsuite>""")
    results = parse(xml, suite_id="s")
    assert results[0].result == "error"


def test_parse_skipped_element_marks_testcase_skipped() -> None:
    xml = _xml("""<testsuite name="s">
      <testcase name="test_skip" classname="t">
        <skipped/>
      </testcase>
    </testsuite>""")
    results = parse(xml, suite_id="s")
    assert results[0].result == "skip"


def test_parse_testsuites_wrapper_supported() -> None:
    """JUnit output may be wrapped in <testsuites> (multi-suite) or be a bare
    <testsuite>. Both forms must parse.
    """
    xml = _xml("""<testsuites>
      <testsuite name="a"><testcase name="t1" classname="c"/></testsuite>
      <testsuite name="b"><testcase name="t2" classname="c"/></testsuite>
    </testsuites>""")
    results = parse(xml, suite_id="s")
    assert {r.name for r in results} == {"t1", "t2"}


def test_parse_multiple_testcases_in_one_suite() -> None:
    xml = _xml("""<testsuite name="s">
      <testcase name="t1" classname="c"/>
      <testcase name="t2" classname="c"/>
      <testcase name="t3" classname="c"><failure/></testcase>
    </testsuite>""")
    results = parse(xml, suite_id="s")
    assert len(results) == 3
    passers = [r for r in results if r.result == "pass"]
    failers = [r for r in results if r.result == "fail"]
    assert len(passers) == 2
    assert len(failers) == 1


def test_parse_classname_missing_falls_back_to_bare_name() -> None:
    """If a testcase has no classname attribute, qualified_name is just the name."""
    xml = _xml("""<testsuite name="s"><testcase name="solo"/></testsuite>""")
    results = parse(xml, suite_id="s")
    assert results[0].qualified_name == "solo"
    assert results[0].classname == ""


def test_parse_is_resistant_to_xxe() -> None:
    """A malicious JUnit payload with an external entity reference must NOT
    resolve the entity (XXE resistance via defusedxml). The parser returns
    gracefully without reading /etc/passwd or expanding the entity.
    """
    xxe_payload = b"""<?xml version="1.0"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<testsuite name="evil"><testcase name="&xxe;" classname="c"/></testsuite>"""
    # defusedxml raises (FORBID_EXTERNAL_REF) rather than resolving.
    results = parse(xxe_payload, suite_id="s")
    # Either we get a graceful empty list, or — if defusedxml escalates — the
    # parser must NOT have inlined the file contents into any record's name.
    for r in results:
        assert "root:" not in r.name  # /etc/passwd content didn't leak in
