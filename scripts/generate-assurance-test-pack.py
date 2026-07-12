#!/usr/bin/env python3
"""Create an ephemeral VG_TEST_FRAMEWORK pack from discovered tests and FR TBT gaps."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
from pathlib import Path


SECURITY_TERMS = {
    "auth", "login", "signup", "otp", "session", "role", "admin", "permission",
    "access", "tenant", "header", "csrf", "xss", "injection", "upload", "metadata",
    "audit", "log", "s3", "storage", "encrypt", "token", "secret", "proxy", "tls",
}


def load_json(path: Path) -> dict:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(errors="replace"))
    except Exception:
        pass
    return {}


def safe_pack_id(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return stem[:140] or "test"


def case_text(item: dict) -> str:
    parts = [item.get("path", ""), item.get("framework", ""), item.get("type", "")]
    for case in item.get("cases", []) or []:
        parts.append(case.get("name", ""))
    return " ".join(str(part) for part in parts).lower()


def assess_native_test(item: dict) -> tuple[str, str]:
    text = case_text(item)
    matched = sorted(term for term in SECURITY_TERMS if term in text)
    if not matched:
        return (
            "candidate_inspiration",
            "Copied for inspection, but no obvious ASVS/JSP-453 assurance terms were detected.",
        )
    if any(term in matched for term in ("auth", "login", "session", "role", "permission", "access", "admin", "upload", "metadata", "audit", "header")):
        return (
            "useful_with_wrapper",
            "Security-relevant behaviour appears present; an assurance wrapper should map the expected control and assertions explicitly.",
        )
    return (
        "candidate_inspiration",
        "Security-adjacent behaviour was detected; use this as design input before counting it as assurance proof.",
    )


def copied_native_entries(target_dir: Path, pack_dir: Path, inventory: dict) -> list[dict]:
    entries: list[dict] = []
    imported_root = pack_dir / "imported"
    for item in inventory.get("files", []) or []:
        rel = item.get("path", "")
        if not rel:
            continue
        src = target_dir / rel
        if not src.exists() or not src.is_file():
            continue
        dest = imported_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        assessment, rationale = assess_native_test(item)
        entries.append({
            "pack_id": f"NATIVE-{safe_pack_id(rel)}",
            "source": "copied_native" if assessment != "useful_with_wrapper" else "wrapper_needed",
            "type": item.get("type", "unit"),
            "runner": item.get("framework", "unknown"),
            "status": "copied",
            "assessment": assessment,
            "safety": "non_destructive",
            "frs": [],
            "native_path": rel,
            "pack_path": str(dest.relative_to(pack_dir)),
            "ruleset_rows": [],
            "assurance_gates": [],
            "cases": item.get("cases", []) or [],
            "rationale": rationale,
        })
    return entries


def existing_asvs_test_for_tbt(target_dir: Path, suggested_path: str) -> Path | None:
    candidate = target_dir / suggested_path
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def planned_tbt_entries(fr_catalog: dict, target_dir: Path | None = None) -> list[dict]:
    frs = [
        fr for fr in fr_catalog.get("frs", []) or []
        if fr.get("lifecycle_status", fr.get("status", "in_scope")) == "in_scope"
    ]
    fr_by_id = {fr.get("id"): fr for fr in frs if fr.get("id")}
    entries: list[dict] = []
    for tbt in fr_catalog.get("tbts", []) or []:
        tbt_id = tbt.get("id")
        if not tbt_id:
            continue
        proved_frs = [fr_id for fr_id in tbt.get("proves", []) or [] if fr_id in fr_by_id]
        if not proved_frs:
            continue
        ruleset_rows: list[dict] = []
        seen_rows: set[tuple[str, str]] = set()
        for row in tbt.get("compliance") or []:
            ruleset = row.get("ruleset")
            row_id = row.get("row")
            if not ruleset or not row_id:
                continue
            key = (ruleset, row_id)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            ruleset_rows.append({"ruleset": ruleset, "row": row_id})
        pack_path = suggested_pack_path(tbt, tbt_id)
        existing_test = existing_asvs_test_for_tbt(target_dir, pack_path) if target_dir else None
        if existing_test:
            entries.append({
                "pack_id": f"EXISTING-{tbt_id}",
                "tbt": tbt_id,
                "frs": proved_frs,
                "title": tbt.get("title") or tbt_id,
                "source": "existing_asvs",
                "type": tbt.get("type", "test"),
                "runner": tbt.get("runner") or runner_for_type(tbt.get("type", "test")),
                "status": "existing",
                "assessment": "needs_review",
                "safety": "review_required",
                "native_path": "",
                "pack_path": pack_path,
                "ruleset_rows": ruleset_rows,
                "assurance_gates": [],
                "cases": [],
                "rationale": (
                    "Existing ASVS-owned test file found at the predictable TBT path. "
                    "Review it for scope, safety, and FR/TBT traceability before approving it to run."
                ),
                "suggested_test": suggested_test_text(fr_by_id, tbt),
            })
            continue
        entries.append({
            "pack_id": tbt_id,
            "tbt": tbt_id,
            "frs": proved_frs,
            "title": tbt.get("title") or tbt_id,
            "source": "planned_tbt",
            "type": tbt.get("type", "test"),
            "runner": tbt.get("runner") or runner_for_type(tbt.get("type", "test")),
            "status": "planned",
            "assessment": "needs_design",
            "safety": "non_destructive",
            "native_path": "",
            "pack_path": pack_path,
            "ruleset_rows": ruleset_rows,
            "assurance_gates": [],
            "cases": [],
            "rationale": "Declared TBT/FR verification target has no generated assurance test implementation in this pack yet.",
            "suggested_test": suggested_test_text(fr_by_id, tbt),
        })
    return entries


def runner_for_type(test_type: str) -> str:
    return {
        "unit": "jest/vitest/pytest",
        "integration": "containerized integration runner",
        "e2e": "playwright",
        "load": "k6",
        "test": "assurance runner",
        "scanner": "scanner",
    }.get(test_type, "assurance runner")


def suggested_pack_path(ref: dict, tbt_id: str) -> str:
    test_type = ref.get("type", "test")
    suffix = "test.js" if test_type in {"unit", "integration", "e2e", "test"} else "spec"
    folder = test_type if test_type in {"unit", "integration", "e2e", "load"} else "planned"
    return f"tests/asvs/{folder}/{tbt_id}.assurance.{suffix}"


def suggested_test_text(fr_by_id: dict[str, dict], tbt: dict) -> str:
    tbt_id = tbt.get("id") or "the mapped TBT"
    titles = [
        fr_by_id[fr_id].get("title") or fr_id
        for fr_id in tbt.get("proves", []) or []
        if fr_id in fr_by_id
    ]
    title = ", ".join(titles) or tbt.get("title") or tbt_id
    test_type = tbt.get("type", "test")
    return (
        f"Design a non-destructive {test_type} assurance test specification for {tbt_id} / {title}. "
        "It should assert observable behaviour, avoid production data, and describe how JUnit evidence would include the TBT in the testcase name."
    )


def write_readme(pack_dir: Path, manifest: dict) -> None:
    lines = [
        "# VG_TEST_FRAMEWORK",
        "",
        "This assurance test pack was generated by ASVS Scanner for this scan run.",
        "It is stored with the report bundle and is not written back to the target project.",
        "",
        "`tests/asvs/` is the ASVS-owned execution surface for generated tests, promoted scaffolds and wrappers.",
        "Existing native project tests remain source-of-truth in their original locations; imported copies are review/provenance inputs only.",
        "",
        "Copied native tests are inputs for assurance assessment. They do not count as compliance proof unless the manifest maps them to a TBT/FR and a JUnit result proves execution.",
        "When wrapper or generated tests are later approved, the TBT should appear in the manifest `tbt` field, file name, test title, and JUnit testcase name/classname.",
        "",
        "Safety policy:",
        f"- Default: {manifest.get('safety_policy', {}).get('default', 'non_destructive')}",
        f"- Project mount: {manifest.get('safety_policy', {}).get('project_mount', 'safe_worktree')}",
        "- Destructive tests are disallowed unless a future explicit review mode is added.",
        "",
        "Summary:",
    ]
    for key, value in sorted((manifest.get("summary") or {}).items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    pack_dir.joinpath("README.md").write_text("\n".join(lines))


def display_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def build_pack(target_dir: Path, report_dir: Path, inventory_path: Path, fr_catalog_path: Path | None) -> dict:
    pack_dir = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK"
    pack_dir.mkdir(parents=True, exist_ok=True)
    inventory = load_json(inventory_path)
    fr_catalog = load_json(fr_catalog_path) if fr_catalog_path else {}

    entries = copied_native_entries(target_dir, pack_dir, inventory)
    entries.extend(planned_tbt_entries(fr_catalog, target_dir))

    summary = {
        "copied_native": sum(1 for item in entries if item["source"] in {"copied_native", "wrapper_needed"}),
        "wrapper_needed": sum(1 for item in entries if item["source"] == "wrapper_needed"),
        "existing_asvs": sum(1 for item in entries if item["source"] == "existing_asvs"),
        "planned_tbt": sum(1 for item in entries if item["source"] == "planned_tbt"),
        "needs_design": sum(1 for item in entries if item["assessment"] == "needs_design"),
        "review_required_existing": sum(1 for item in entries if item["source"] == "existing_asvs" and item["safety"] == "review_required"),
        "not_counted_as_evidence": sum(1 for item in entries if item["status"] in {"copied", "planned"} or item.get("safety") == "review_required"),
    }
    manifest = {
        "schema_version": 1,
        "name": "VG_TEST_FRAMEWORK",
        "mode": "ephemeral",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "target_dir": str(target_dir),
        "source_inventory": display_path(inventory_path, report_dir),
        "summary": summary,
        "safety_policy": {
            "default": "non_destructive",
            "project_mount": "safe_worktree",
            "network": "disabled unless scanner/runtime flags explicitly provide a target URL",
            "writes_allowed": ["report bundle", "temporary runner workspace"],
        },
        "tests": entries,
    }
    (pack_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    write_readme(pack_dir, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--test-inventory", required=True)
    parser.add_argument("--fr-catalog", default=None)
    args = parser.parse_args()
    manifest = build_pack(
        Path(args.target_dir),
        Path(args.report_dir),
        Path(args.test_inventory),
        Path(args.fr_catalog) if args.fr_catalog else None,
    )
    print(
        "assurance-test-pack: "
        f"{manifest['summary'].get('copied_native', 0)} copied, "
        f"{manifest['summary'].get('existing_asvs', 0)} existing ASVS tests, "
        f"{manifest['summary'].get('planned_tbt', 0)} planned TBT entries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
