"""Parse JUnit XML output into per-testcase evidence records.

JUnit XML is the de-facto interchange format. pytest, jest (via
jest-junit), gradle, maven surefire, and many others all emit it.

Each <testcase> becomes one record. The caller (orchestrator) maps
records to FRs via the mapping pack using the test's fully-qualified
name: <classname>::<name>.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


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
    except ET.ParseError as exc:
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


def to_evidence_records(
    results: list[TestCaseResult],
    run_id: str,
    project_path: str,
    mapping_index: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert test results into evidence record dicts.

    `mapping_index` is a dict of (test name pattern from mapping pack) → fr_id.
    We use fnmatch to test each result's qualified_name against each pattern;
    a single test can map to multiple FRs.

    Returns dicts shaped for EvidenceRepository.insert().
    """
    import fnmatch

    out: list[dict[str, Any]] = []
    for r in results:
        for pattern, fr_id in mapping_index.items():
            if fnmatch.fnmatchcase(r.qualified_name, pattern):
                out.append({
                    "project_path": project_path,
                    "fr_id": fr_id,
                    "run_id": run_id,
                    "type": "unit-test",  # suite.type would be more accurate
                    "source": {
                        "kind": "pytest",
                        "test_name": r.qualified_name,
                        "suite_id": r.suite_id,
                        "run_kind": "worker-run",
                        "run_id": run_id,
                    },
                    "result": "pass" if r.result == "pass" else "fail",
                    "notes": (r.failure_message or "")[:500] or None,
                })
    return out
