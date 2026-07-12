#!/usr/bin/env python3
"""Promote selected TBT specifications into review-required test scaffolds.

The scaffolds are written into the report-local VG_TEST_FRAMEWORK pack under
tests/asvs/. They are intentionally skipped by default and are not counted as
evidence until a reviewer implements them, removes the skip, runs them, and
imports observed JUnit/scanner output.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from artifact_hashing import file_sha256, write_hash_sidecar


DEFAULT_TBTS = ["TBT-018", "TBT-019", "TBT-021"]


def load_json(path: Path) -> dict[str, Any]:
    if path.exists() and path.stat().st_size > 0:
        return json.loads(path.read_text(errors="replace"))
    return {}


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return slug[:120] or "assurance-test"


def runner_for(test_type: str) -> str:
    return {
        "unit": "jest/vitest with JUnit reporter",
        "integration": "containerized integration runner with JUnit reporter",
        "e2e": "Playwright with JUnit reporter",
        "load": "k6 or equivalent load runner with JUnit-compatible summary export",
        "scanner": "scanner mapping evidence",
        "manual": "manual evidence checklist",
        "manual_review": "manual evidence checklist",
    }.get(test_type, "assurance runner with JUnit reporter")


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


def related_rows(tbt: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in tbt.get("compliance") or []:
        key = (row.get("ruleset", ""), row.get("row", ""))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        rows.append({"ruleset": key[0], "row": key[1]})
    return rows


def related_gates(frs: list[dict[str, Any]]) -> list[str]:
    gates: list[str] = []
    for fr in frs:
        for value in fr.get("assurance_gates", []) or []:
            if isinstance(value, str) and value not in gates:
                gates.append(value)
    return gates


def source_references(frs: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for fr in frs:
        for ref in fr.get("implemented_by", []) or []:
            path = ref.get("path", "")
            label = ref.get("label")
            if path and label:
                refs.append(f"{path} - {label}")
            elif path:
                refs.append(path)
    return refs[:12]


def assertion_plan(test_type: str, frs: list[dict[str, Any]]) -> list[str]:
    joined = " ".join(
        [str(fr.get("title", "")) for fr in frs]
        + [str(fr.get("description", "")) for fr in frs]
    ).lower()
    plan = [
        "Arrange disposable fixtures only; do not mutate production data.",
        "Act through documented product APIs or UI paths that already exist.",
        "Assert both the allowed path and at least one denied/negative path where relevant.",
        "Export JUnit XML with the TBT identifier in classname or testcase name.",
    ]
    if any(word in joined for word in ["auth", "login", "session", "lockout"]):
        plan.insert(2, "Verify authentication/session state changes and failed-attempt behaviour explicitly.")
    if any(word in joined for word in ["audit", "marking", "document", "delete", "removal"]):
        plan.insert(2, "Verify actor, action, target and timestamp are written to durable audit evidence.")
    if any(word in joined for word in ["role", "group", "permission", "administrator"]):
        plan.insert(2, "Verify only authorized actors can perform the role/group operation.")
    if test_type == "e2e":
        plan.insert(1, "Use Playwright against a disposable environment seeded with test users.")
    if test_type == "load":
        plan.insert(1, "Keep write volume bounded and enforce explicit latency/error thresholds.")
    return plan


def scaffold_content(
    *,
    tbt: dict[str, Any],
    frs: list[dict[str, Any]],
    rows: list[dict[str, str]],
    status: str,
) -> str:
    tbt_id = tbt.get("id", "TBT-UNKNOWN")
    fr_ids = [fr.get("id", "") for fr in frs if fr.get("id")]
    title = tbt.get("title") or (frs[0].get("title") if frs else tbt_id)
    test_type = tbt.get("type", "test")
    refs = source_references(frs)
    row_text = ", ".join(f"{row['ruleset']} {row['row']}" for row in rows) or "not mapped"
    ref_text = "\n".join(f" * - {ref}" for ref in refs) or " * - No source reference declared in FR catalog."
    plan_text = "\n".join(f" * {idx}. {item}" for idx, item in enumerate(assertion_plan(test_type, frs), start=1))
    description = frs[0].get("description") if frs else title
    return f"""/*
 * Generated by VibeGuide Assurance Engine.
 *
 * Status: review-required scaffold, not evidence.
 * TBT: {tbt_id}
 * FRs: {', '.join(fr_ids) or 'none'}
 * Current evidence state: {status}
 * Compliance rows: {row_text}
 * Recommended runner: {runner_for(test_type)}
 *
 * Source references:
{ref_text}
 *
 * Assurance intent:
 * {description}
 *
 * Implementation plan:
{plan_text}
 *
 * Remove describe.skip only after replacing the placeholders with real,
 * non-destructive fixtures and confirming JUnit output includes {tbt_id}.
 */

describe.skip("[{tbt_id}] {title}", () => {{
  test("[{tbt_id}] produces observed assurance evidence for {', '.join(fr_ids) or 'mapped FR'}", async () => {{
    // TODO: Arrange disposable fixtures and test actors.
    // TODO: Exercise the documented product behaviour that proves the TBT.
    // TODO: Assert allowed, denied and audit/evidence side effects as applicable.
    // TODO: Export JUnit XML and import it with --junit-xml before counting evidence.
    throw new Error("{tbt_id} scaffold requires product-specific implementation before execution");
  }});
}});
"""


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
    manifest["evidence_files"] = [entries[key] for key in sorted(entries)]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def promote(report_dir: Path, selected_tbts: list[str]) -> dict[str, Any]:
    fr_catalog = load_json(report_dir / "fr-catalog.snapshot.json")
    evidence_bundle = load_json(report_dir / "evidence-bundle.json")
    manifest_path = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "manifest.json"
    manifest = load_json(manifest_path)
    if not manifest:
        raise SystemExit(f"assurance test manifest not found: {manifest_path}")

    pack_dir = manifest_path.parent
    fr_by_id = {fr.get("id"): fr for fr in fr_catalog.get("frs", []) or [] if fr.get("id")}
    tbt_by_id = {tbt.get("id"): tbt for tbt in fr_catalog.get("tbts", []) or [] if tbt.get("id")}
    promoted: list[dict[str, Any]] = []
    written: list[Path] = []

    for tbt_id in selected_tbts:
        tbt = tbt_by_id.get(tbt_id)
        if not tbt:
            continue
        frs = [fr_by_id[fr_id] for fr_id in tbt.get("proves", []) or [] if fr_id in fr_by_id]
        rows = related_rows(tbt)
        status = tbt_result_status(evidence_bundle, tbt_id)
        test_type = tbt.get("type", "test")
        rel = Path("tests") / "asvs" / test_type / f"{safe_slug(tbt_id)}.assurance.test.js"
        path = pack_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(scaffold_content(tbt=tbt, frs=frs, rows=rows, status=status))
        written.append(path)
        promoted.append({
            "pack_id": f"GENERATED-{tbt_id}",
            "tbt": tbt_id,
            "frs": [fr.get("id") for fr in frs if fr.get("id")],
            "title": tbt.get("title") or (frs[0].get("title") if frs else tbt_id),
            "source": "generated",
            "type": test_type,
            "runner": runner_for(test_type),
            "status": "generated",
            "assessment": "needs_design",
            "safety": "review_required",
            "pack_path": str(rel),
            "ruleset_rows": rows,
            "assurance_gates": related_gates(frs),
            "rationale": (
                "Promoted from a missing/partial/failed TBT specification into a "
                "review-required scaffold. It is not evidence until implemented and run."
            ),
            "suggested_test": (
                f"Implement {tbt_id} in a disposable test environment and export observed JUnit evidence."
            ),
        })

    if not promoted:
        raise SystemExit("no selected TBTs were found in fr-catalog.snapshot.json")

    selected_set = {item["tbt"] for item in promoted}
    existing_tests = {
        item.get("pack_id"): item
        for item in manifest.get("tests", []) or []
        if item.get("pack_id")
        and not (
            item.get("tbt") in selected_set
            and item.get("status") in {"planned", "generated"}
            and item.get("source") in {"planned_tbt", "generated"}
        )
    }
    for item in promoted:
        existing_tests[item["pack_id"]] = item
    manifest["tests"] = [existing_tests[key] for key in sorted(existing_tests)]
    summary = manifest.setdefault("summary", {})
    summary["generated_scaffolds"] = len([
        item for item in manifest["tests"] if item.get("source") == "generated"
    ])
    summary["review_required_scaffolds"] = len([
        item for item in manifest["tests"] if item.get("safety") == "review_required"
    ])
    manifest["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    update_report_manifest(report_dir, [manifest_path, *written])
    return {"promoted": promoted, "manifest": str(manifest_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument(
        "--tbt",
        action="append",
        default=[],
        help="TBT identifier to promote. May be repeated. Defaults to TBT-018, TBT-019 and TBT-021.",
    )
    args = parser.parse_args()
    selected = args.tbt or DEFAULT_TBTS
    result = promote(args.report_dir, selected)
    ids = ", ".join(item["tbt"] for item in result["promoted"])
    print(f"promoted {len(result['promoted'])} assurance scaffolds ({ids}) under {Path(result['manifest']).parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
