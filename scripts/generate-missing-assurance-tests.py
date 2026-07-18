#!/usr/bin/env python3
"""Generate reviewable assurance test specifications for missing TBT evidence.

This intentionally does not write executable product tests or claim evidence.
It creates a safe, report-local test design pack that can later be promoted to
unit/integration/e2e/load code after human review.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from artifact_hashing import file_sha256, write_hash_sidecar


def load_json(path: Path) -> dict[str, Any]:
    if path.exists() and path.stat().st_size > 0:
        return json.loads(path.read_text(errors="replace"))
    return {}


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return slug[:120] or "assurance-test"


def tbt_result_status(evidence_bundle: dict[str, Any], tbt_id: str) -> str:
    records = [
        item
        for item in evidence_bundle.get("evidence", []) or []
        if item.get("produced_by") == tbt_id
    ]
    if not records:
        return "missing"
    statuses = {item.get("result_status", "missing") for item in records}
    if "failed" in statuses:
        return "failed"
    if "passed" in statuses and "missing" in statuses:
        return "partial"
    if "passed" in statuses:
        return "passed"
    if "manual_review" in statuses:
        return "manual_review"
    return "missing"


def runner_for(test_type: str) -> str:
    return {
        "unit": "jest/vitest with JUnit reporter",
        "integration": "containerized integration runner with JUnit reporter",
        "e2e": "Playwright with JUnit reporter",
        "load": "k6 or equivalent load runner with JUnit-compatible summary export",
        "scanner": "scanner mapping evidence",
        "manual": "manual evidence checklist",
    }.get(test_type, "assurance runner with JUnit reporter")


def assertion_shape(test_type: str, fr: dict[str, Any]) -> list[str]:
    title = (fr.get("title") or "").lower()
    assertions = [
        "The observed behaviour matches the FR description without relying on production data.",
        "The test records a JUnit testcase whose classname or name contains the TBT identifier.",
        "The test leaves the project state clean, or uses disposable fixtures with explicit teardown.",
    ]
    if "session" in title or "authentication" in title or "login" in title:
        assertions.insert(0, "Authentication/session state changes are enforced for the tested actor.")
    if "audit" in title or "log" in title:
        assertions.insert(0, "A durable audit/log record is produced with actor, action, target and timestamp.")
    if "role" in title or "permission" in title or "admin" in title:
        assertions.insert(0, "Unauthorized actors are denied and authorized actors receive only the expected capability.")
    if "upload" in title or "ingestion" in title or "document" in title:
        assertions.insert(0, "File/document fixtures are sanitized, bounded in size and removed after the test.")
    if test_type == "e2e":
        assertions.insert(0, "The browser journey verifies visible user outcome and backend side effect where applicable.")
    if test_type == "load":
        assertions.insert(0, "The scenario records latency/error thresholds without destructive write volume.")
    return assertions


def format_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- Not mapped to compliance rows yet.\n"
    return "".join(
        f"- {row.get('ruleset', '')} `{row.get('row', '')}`\n"
        for row in rows
    )


def write_spec(
    spec_path: Path,
    *,
    tbt: dict[str, Any],
    frs: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    status: str,
) -> None:
    tbt_id = tbt.get("id", "TBT-UNKNOWN")
    test_type = tbt.get("type", "test")
    primary_fr = frs[0] if frs else {}
    fr_title = primary_fr.get("title", tbt_id)
    source_refs = []
    for fr in frs:
        for ref in fr.get("implemented_by", []) or []:
            source_refs.append(ref)
    source_lines = []
    for ref in source_refs[:12]:
        label = f" - {ref.get('label')}" if ref.get("label") else ""
        source_lines.append(f"- `{ref.get('path', '')}`{label}")
    if not source_lines:
        source_lines = ["- No source reference declared in FR catalog."]

    assertions = assertion_shape(test_type, primary_fr)
    expected_case = f"{tbt_id} {primary_fr.get('id', '')} {fr_title}".strip()
    content = f"""# {tbt_id} Assurance Test Specification

## Status

- Generated: proposed specification only
- Current evidence state: {status}
- Evidence policy: {tbt.get('evidence_policy', 'automated_required')}
- Test type: {test_type}
- Recommended runner: {runner_for(test_type)}

## Traceability

- TBT: `{tbt_id}`
- FRs: {', '.join(f'`{fr.get("id", "")}`' for fr in frs) or 'none'}
- Title: {tbt.get('title') or fr_title}

## Compliance Rows

{format_rows(rows)}
## Source References

{chr(10).join(source_lines)}

## Proposed Test Intent

Design a non-destructive {test_type} assurance test for `{tbt_id}` that proves:

> {primary_fr.get('description') or fr_title}

The test must not invent product behaviour. If the referenced source does not expose the required behaviour, leave this as a blocked specification and update the FR/TBT config instead of fabricating endpoints or assertions.

## Preconditions

- Use disposable fixtures and test users only.
- Do not call live external systems unless the runner is explicitly configured with a safe test endpoint.
- Do not mutate production data.
- Mock or containerize external dependencies where possible.
- Ensure the TBT appears in the testcase name and generated JUnit output.

## Assertions

{chr(10).join(f'- {item}' for item in assertions)}

## Expected Evidence

- JUnit file: `reports/junit.xml`
- Expected testcase classname/name contains: `{expected_case}`
- Result may be counted only after the test has actually run and produced observed pass/fail evidence.

## Implementation Notes

- Preferred ASVS execution location after approval: `tests/asvs/{tbt.get('type', 'test')}/{tbt_id}.assurance.test.js`
- Existing native tests should remain in their original locations; use `tests/asvs/` for assurance-owned wrappers or new assurance tests.
- Keep the test isolated from the application source tree until it is reviewed.
- If this cannot be automated safely, classify the TBT as `manual_evidence` and attach the manual artifact instead.
"""
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(content)


def build_specs(report_dir: Path) -> dict[str, Any]:
    fr_catalog = load_json(report_dir / "fr-catalog.snapshot.json")
    evidence_bundle = load_json(report_dir / "evidence-bundle.json")
    manifest_path = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "manifest.json"
    manifest = load_json(manifest_path)
    pack_dir = manifest_path.parent
    fr_by_id = {fr.get("id"): fr for fr in fr_catalog.get("frs", []) or [] if fr.get("id")}
    generated: list[dict[str, Any]] = []

    for tbt in fr_catalog.get("tbts", []) or []:
        tbt_id = tbt.get("id")
        if not tbt_id:
            continue
        status = tbt_result_status(evidence_bundle, tbt_id)
        if status not in {"missing", "partial", "failed"}:
            continue
        frs = [fr_by_id[fr_id] for fr_id in tbt.get("proves", []) or [] if fr_id in fr_by_id]
        rows: list[dict[str, Any]] = []
        seen_rows: set[tuple[str, str]] = set()
        for row in tbt.get("compliance") or []:
            key = (row.get("ruleset", ""), row.get("row", ""))
            if key in seen_rows:
                continue
            seen_rows.add(key)
            rows.append({"ruleset": key[0], "row": key[1]})
        spec_rel = Path("specifications") / tbt.get("type", "test") / f"{safe_slug(tbt_id)}.assurance-spec.md"
        write_spec(pack_dir / spec_rel, tbt=tbt, frs=frs, rows=rows, status=status)
        generated.append({
            "tbt": tbt_id,
            "frs": [fr.get("id") for fr in frs],
            "status": "proposed_specification",
            "evidence_state": status,
            "type": tbt.get("type", "test"),
            "runner": runner_for(tbt.get("type", "test")),
            "spec_path": str(spec_rel),
            "ruleset_rows": rows,
        })

    manifest.setdefault("generated_specifications", [])
    existing = {
        item.get("tbt"): item
        for item in manifest.get("generated_specifications", [])
        if item.get("tbt")
    }
    for item in generated:
        existing[item["tbt"]] = item
    manifest["generated_specifications"] = [
        existing[key] for key in sorted(existing)
    ]
    summary = manifest.setdefault("summary", {})
    summary["generated_specifications"] = len(manifest["generated_specifications"])
    summary["still_not_counted_as_evidence"] = summary.get("not_counted_as_evidence", 0)
    manifest["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    runbook = pack_dir / "RUNBOOK.md"
    runbook.write_text(
        "# VG_TEST_FRAMEWORK Runbook\n\n"
        "Generated assurance specifications are design artifacts, not evidence.\n\n"
        "To convert one into executable evidence:\n\n"
        "1. Review the specification and referenced source files.\n"
        "2. Implement only behaviour that already exists or is explicitly documented under `tests/asvs/` in the assurance-owned execution surface.\n"
        "3. Keep the TBT identifier in the test file, test title and JUnit testcase name.\n"
        "4. Run the test in a disposable/containerized environment.\n"
        "5. Export JUnit XML and rerun the scanner with `--junit-xml <path>`.\n\n"
        "Do not count a specification as passing evidence until observed JUnit/scanner output exists.\n"
    )
    update_report_manifest(report_dir, [manifest_path, runbook, *[
        pack_dir / item["spec_path"] for item in generated
    ]])
    return {"generated": generated, "manifest": str(manifest_path)}


def update_report_manifest(report_dir: Path, paths: list[Path]) -> None:
    manifest_path = report_dir / "evidence-manifest.json"
    if not manifest_path.exists():
        return
    manifest = load_json(manifest_path)
    entries = {
        item.get("file"): item
        for item in manifest.get("evidence_files", []) or []
        if item.get("file")
    }
    for path in paths:
        if not path.is_file():
            continue
        rel = path.relative_to(report_dir)
        rel_str = str(rel)
        digest = file_sha256(path)
        entries[rel_str] = {
            "file": rel_str,
            "bytes": path.stat().st_size,
            "sha256": digest,
        }
        write_hash_sidecar(report_dir, path)
    manifest["evidence_files"] = [
        entries[key] for key in sorted(entries)
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    result = build_specs(args.report_dir)
    print(
        f"generated {len(result['generated'])} assurance test specifications "
        f"under {Path(result['manifest']).parent}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
