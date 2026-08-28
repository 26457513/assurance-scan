"""Parse JUnit XML output into normalized per-testcase results.

JUnit XML is the de-facto interchange format. pytest, jest (via
jest-junit), gradle, maven surefire, and many others all emit it.

Each <testcase> becomes one record. The caller (orchestrator) maps
records to FRs via the mapping pack using the test's fully-qualified
name: <classname>::<name>.
"""
from __future__ import annotations

import logging
from defusedxml import ElementTree as ET  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]
from dataclasses import dataclass


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TestCaseResult:
    """One test case, normalized across JUnit emitters."""

    suite_id: str
    name: str                       # testcase name attribute
    classname: str                  # testcase classname attribute (file path or class)
    qualified_name: str             # "<classname>::<name>" — what mapping packs match against
    result: str                     # 'pass' | 'fail' | 'error' | 'skip'
    elapsed_seconds: float | None
    failure_message: str | None


def parse(junit_xml: bytes, suite_id: str) -> list[TestCaseResult]:
    """Parse JUnit XML. Returns one TestCaseResult per <testcase>."""
    if not junit_xml:
        return []
    try:
        root = ET.fromstring(junit_xml)
    except (ET.ParseError, DefusedXmlException) as exc:
        # ParseError: malformed XML. DefusedXmlException: XXE / entity-bomb
        # attempt blocked by defusedxml — must not crash the parser.
        log.warning("invalid JUnit XML from suite %s: %s", suite_id, exc)
        return []

    results: list[TestCaseResult] = []
    # JUnit XML can be wrapped in <testsuites> or be a single <testsuite>.
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    for suite in suites:
        for case in suite.findall("testcase"):
            results.append(_parse_case(case, suite_id))
    return results


def _parse_case(case: ET.Element, suite_id: str) -> TestCaseResult:
    name = case.get("name", "")
    classname = case.get("classname", "")
    qualified = f"{classname}::{name}" if classname else name

    # Result is determined by which child elements are present.
    failure = case.find("failure")
    error = case.find("error")
    skipped = case.find("skipped")

    if error is not None:
        result = "error"
        message = error.get("message") or (error.text or "").strip()
    elif failure is not None:
        result = "fail"
        message = failure.get("message") or (failure.text or "").strip()
    elif skipped is not None:
        result = "skip"
        message = skipped.get("message") or None
    else:
        result = "pass"
        message = None

    time_str = case.get("time")
    elapsed: float | None = None
    if time_str:
        try:
            elapsed = float(time_str)
        except ValueError:
            pass

    return TestCaseResult(
        suite_id=suite_id,
        name=name,
        classname=classname,
        qualified_name=qualified,
        result=result,
        elapsed_seconds=elapsed,
        failure_message=message,
    )
