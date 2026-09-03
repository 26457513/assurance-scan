"""Contract tests for bounded, origin-neutral finding source context."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from app.modules.atomic.ingestion.source_context import (
    SourceContextLimits,
    extract_source_contexts,
    sanitize_source_contexts,
    validate_source_context_links,
)
from app.modules.atomic.local_cli.scanner_runner import findings_document
from app.modules.atomic.scanning.finding_parser import ParsedFinding, TrivyJsonParser
from app.modules.atomic.scanning.result_builder import ci_payload
from app.modules.shared.contracts.findings import FindingPayload


def _finding(**overrides: object) -> FindingPayload:
    value: FindingPayload = {
        "scanner": "semgrep",
        "rule_id": "python.test",
        "severity": "HIGH",
        "file_path": "src/app.py",
        "line_start": 8,
        "line_end": 8,
        "message": "unsafe call",
        "compliance_tags": [],
    }
    value.update(overrides)  # type: ignore[typeddict-item]
    return value


def _snapshot(tmp_path: Path, text: str) -> Path:
    root = tmp_path / "snapshot"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text(text, encoding="utf-8")
    return root


def test_extracts_eleven_line_window_and_stable_keys(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, "\n".join(f"line {number}" for number in range(1, 20)))

    first = extract_source_contexts(root, [_finding()], schema_version=1)
    second = extract_source_contexts(root, [_finding()], schema_version=1)

    assert first == second
    assert first.findings[0]["finding_key"]
    context = first.contexts[0]
    assert context["available"] is True
    assert context["window_start"] == 3
    assert context["window_end"] == 13
    assert [line["number"] for line in context["lines"]] == list(range(3, 14))
    validate_source_context_links(first.findings, first.contexts)


def test_duplicate_findings_get_distinct_keys_and_share_exact_window(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, "\n".join(f"line {number}" for number in range(1, 15)))

    result = extract_source_contexts(root, [_finding(), _finding()], schema_version=1)

    assert result.findings[0]["finding_key"] != result.findings[1]["finding_key"]
    assert len(result.contexts) == 1
    assert result.contexts[0]["finding_keys"] == [
        result.findings[0]["finding_key"],
        result.findings[1]["finding_key"],
    ]


def test_long_highlight_is_anchored_and_marked_truncated(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, "\n".join(f"line {number}" for number in range(1, 30)))

    result = extract_source_contexts(
        root,
        [_finding(line_start=4, line_end=20)],
        schema_version=1,
    )

    context = result.contexts[0]
    assert (context["window_start"], context["window_end"]) == (4, 14)
    assert context["highlight_end"] == 20
    assert context["highlight_truncated"] is True


@pytest.mark.parametrize(
    ("finding", "reason"),
    [
        (_finding(file_path=None), "missing_path"),
        (_finding(line_start=None, line_end=None), "missing_line"),
        (_finding(file_path="../outside.py"), "invalid_path"),
        (_finding(file_path="src/missing.py"), "missing_file"),
        (_finding(line_start=999, line_end=999), "untrusted_range"),
    ],
)
def test_unavailable_reasons_do_not_drop_findings(
    tmp_path: Path,
    finding: FindingPayload,
    reason: str,
) -> None:
    root = _snapshot(tmp_path, "safe\n")

    result = extract_source_contexts(root, [finding], schema_version=1)

    assert len(result.findings) == 1
    assert result.contexts[0]["available"] is False
    assert result.contexts[0]["unavailable_reason"] == reason
    assert "lines" not in result.contexts[0]


def test_redacts_secrets_and_truncates_unicode_on_byte_boundary(tmp_path: Path) -> None:
    secret = "Bearer abcdefghijklmnopqrstuvwxyz"
    root = _snapshot(tmp_path, f"before\n{secret} {'é' * 100}\nafter\n")

    result = extract_source_contexts(
        root,
        [_finding(line_start=2, line_end=2)],
        schema_version=1,
        limits=SourceContextLimits(max_line_bytes=40),
    )

    context = result.contexts[0]
    assert context["redaction_changed"] is True
    rendered = context["lines"][1]
    assert secret not in rendered["text"]
    assert len(rendered["text"].encode("utf-8")) <= 40
    assert rendered["truncated"] is True


def test_sanitizer_rejects_full_file_exfiltration_shape(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, "one\ntwo\n")
    result = extract_source_contexts(root, [_finding(line_start=1, line_end=1)], schema_version=1)
    malicious = dict(result.contexts[0])
    malicious["lines"] = [
        {"number": number, "text": "x", "truncated": False}
        for number in range(1, 13)
    ]

    with pytest.raises(ValueError, match="line count"):
        sanitize_source_contexts([malicious])  # type: ignore[list-item]


def test_link_validation_rejects_orphan_key(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, "one\ntwo\n")
    result = extract_source_contexts(root, [_finding(line_start=1, line_end=1)], schema_version=1)
    context = dict(result.contexts[0])
    context["finding_keys"] = ["00000000-0000-4000-8000-000000000000"]

    with pytest.raises(ValueError, match="orphan"):
        validate_source_context_links(result.findings, [context])  # type: ignore[list-item]


def test_local_and_github_producers_emit_equivalent_context(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, "one\ntwo\nunsafe()\nfour\nfive\n")
    parsed = ParsedFinding(
        scanner_kind="semgrep",
        rule_id="python.test",
        severity="HIGH",
        file_path="src/app.py",
        line_start=3,
        line_end=3,
        message="unsafe call",
    )

    local = findings_document(
        cast(Any, [parsed]),
        [{"kind": "semgrep", "status": "completed"}],
        snapshot_root=root,
    )
    github = ci_payload(
        cast(Any, [parsed]),
        {"semgrep": "ok"},
        {"semgrep": 1.0},
        repo="owner/repo",
        run_url=None,
        source_root=root,
    )

    assert local["findings"][0]["finding_key"] == github["findings"][0]["finding_key"]
    assert local["source_contexts"] == github["source_contexts"]


def test_trivy_configuration_range_produces_source_context(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    root.mkdir()
    (root / "Dockerfile").write_text(
        "\n".join(
            (
                "FROM python:3.13-slim",
                "WORKDIR /app",
                "COPY . .",
                "RUN pip install -r requirements.txt",
                "CMD [\"python\", \"app.py\"]",
            )
        ),
        encoding="utf-8",
    )
    raw = b"""{
      "Results": [{
        "Target": "/src/Dockerfile",
        "Misconfigurations": [{
          "ID": "DS-0002",
          "Title": "Root user",
          "Description": "Container runs as root.",
          "Severity": "HIGH",
          "CauseMetadata": {"StartLine": 1, "EndLine": 5}
        }]
      }]
    }"""
    parsed = TrivyJsonParser(scanner_kind="trivy-config", mode="config").parse(raw)

    document = findings_document(
        cast(Any, parsed),
        [{"kind": "trivy-config", "status": "completed"}],
        snapshot_root=root,
    )

    finding = document["findings"][0]
    context = document["source_contexts"][0]
    assert finding["file_path"] == "Dockerfile"
    assert (finding["line_start"], finding["line_end"]) == (1, 5)
    assert context["available"] is True
    assert (context["highlight_start"], context["highlight_end"]) == (1, 5)
    assert [line["number"] for line in context["lines"]] == [1, 2, 3, 4, 5]
