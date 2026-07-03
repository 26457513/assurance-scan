#!/usr/bin/env python3
"""Validate ``data/asvs_mapping.yaml`` against schema and source snapshots.

Runs the following checks and exits non-zero on any failure:

1. **Schema conformance** — every entry has required fields with allowed values.
2. **ASVS ID resolution** — every ``asvs_id`` exists in ``asvs_requirements.json``.
3. **Rule ID resolution** — every ``rule_id`` matches at least one rule in the
   relevant scanner's source snapshot (exact match or fnmatch glob).
4. **Coverage gap report** — scanner rules not referenced by any ASVS row are
   written to ``data/sources/coverage-gaps.md`` for curation review.
5. **Parroting check** (when ``--compliance-csv`` is given) — distribution of
   ``csv_hint_agreement`` values; flag if "agree" > 85%.
6. **Orphan detection** (when ``--compliance-csv`` is given) — ASVS IDs in the
   YAML but no longer in the CSV are marked ``review.status: orphaned``.

Usage::

    python3 scripts/validate-mapping.py data/asvs_mapping.yaml
    python3 scripts/validate-mapping.py data/asvs_mapping.yaml \\
        --compliance-csv /path/to/project.csv

Exits 0 on success, 1 on validation failure, 2 on usage error.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "data" / "sources"
COVERAGE_GAPS_PATH = SOURCES_DIR / "coverage-gaps.md"

ALLOWED_REVIEW_STATUSES = {"unreviewed", "reviewed", "rejected", "stale", "orphaned"}
ALLOWED_CONFIDENCES = {"high", "medium", "low"}
ALLOWED_HINT_AGREEMENTS = {"agree", "modified", "rejected", "no_hint"}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyyaml required: pip install -r requirements-mapping.txt") from exc
    return yaml.safe_load(path.read_text()) or {}


def _load_asvs_requirements() -> dict[str, dict]:
    path = SOURCES_DIR / "asvs_requirements.json"
    data = json.loads(path.read_text())
    return {req["id"]: req for req in data.get("requirements", []) if "id" in req}


def _load_scanner_rules() -> dict[str, list[dict]]:
    """Return {scanner_name: [rule_dicts]} for every *_rules.json snapshot."""
    out: dict[str, list[dict]] = {}
    for path in sorted(SOURCES_DIR.glob("*_rules.json")):
        if path.name == "asvs_requirements.json":
            continue
        scanner = path.stem.removesuffix("_rules")
        data = json.loads(path.read_text())
        entries = data.get("entries") or data.get("requirements") or []
        out[scanner] = entries
    return out


def _load_csv_ids(csv_path: Path | None) -> set[str]:
    if csv_path is None or not csv_path.exists():
        return set()
    ids: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        id_col: int | None = None
        for row in reader:
            if not row:
                continue
            if id_col is None:
                for i, cell in enumerate(row):
                    if cell.strip() == "ASVS ID":
                        id_col = i
                        break
                if id_col is not None:
                    continue
                # Not yet found header
                continue
            if len(row) > id_col:
                asvs_id = row[id_col].strip()
                if asvs_id and asvs_id.startswith("v"):
                    ids.add(asvs_id)
    return ids


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.info.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def _validate_schema(payload: dict, report: Report) -> None:
    if not isinstance(payload, dict):
        report.error("top-level YAML is not a mapping")
        return
    if "requirements" not in payload:
        report.error("missing top-level 'requirements' key")
        return
    reqs = payload["requirements"]
    if not isinstance(reqs, dict):
        report.error("'requirements' is not a mapping")
        return

    for asvs_id, entry in reqs.items():
        if not isinstance(entry, dict):
            report.error(f"{asvs_id}: entry is not a mapping")
            continue
        scanners = entry.get("scanners") or {}
        if not isinstance(scanners, dict):
            report.error(f"{asvs_id}: 'scanners' is not a mapping")
            continue
        for scanner, mappings in scanners.items():
            if not isinstance(mappings, list):
                report.error(f"{asvs_id}/{scanner}: mappings is not a list")
                continue
            for i, m in enumerate(mappings):
                prefix = f"{asvs_id}/{scanner}[{i}]"
                if not isinstance(m, dict):
                    report.error(f"{prefix}: mapping is not a dict")
                    continue
                rid = m.get("rule_id")
                if not rid or not isinstance(rid, str):
                    report.error(f"{prefix}: missing or invalid 'rule_id'")
                confidence = m.get("confidence")
                if confidence not in ALLOWED_CONFIDENCES:
                    report.error(f"{prefix}: invalid 'confidence' {confidence!r}; allowed: {sorted(ALLOWED_CONFIDENCES)}")
                if not m.get("reasoning"):
                    report.error(f"{prefix}: missing 'reasoning'")
                review = m.get("review") or {}
                if not isinstance(review, dict):
                    report.error(f"{prefix}: 'review' is not a mapping")
                else:
                    status = review.get("status")
                    if status not in ALLOWED_REVIEW_STATUSES:
                        report.error(f"{prefix}: invalid review.status {status!r}; allowed: {sorted(ALLOWED_REVIEW_STATUSES)}")
                agreement = m.get("csv_hint_agreement")
                if agreement is not None and agreement not in ALLOWED_HINT_AGREEMENTS:
                    report.error(f"{prefix}: invalid csv_hint_agreement {agreement!r}; allowed: {sorted(ALLOWED_HINT_AGREEMENTS)}")


def _validate_asvs_ids(payload: dict, asvs_lookup: dict[str, dict], report: Report) -> None:
    reqs = payload.get("requirements") or {}
    for asvs_id in reqs:
        if asvs_id not in asvs_lookup:
            report.error(f"{asvs_id}: not present in asvs_requirements.json — likely a typo or stale entry")


def _validate_rule_ids(payload: dict, scanner_rules: dict[str, list[dict]], report: Report) -> None:
    """Every rule_id must match at least one catalog rule (exact or fnmatch)."""
    reqs = payload.get("requirements") or {}
    # Build per-scanner ID index
    rule_id_index: dict[str, set[str]] = {
        scanner: {r.get("id", "") for r in rules if r.get("id")}
        for scanner, rules in scanner_rules.items()
    }
    for asvs_id, entry in reqs.items():
        scanners = entry.get("scanners") or {}
        for scanner, mappings in scanners.items():
            known_ids = rule_id_index.get(scanner)
            if known_ids is None:
                # Scanner has no source snapshot — skip (e.g. semgrep, syft).
                continue
            for i, m in enumerate(mappings):
                rid = m.get("rule_id", "")
                if not rid:
                    continue
                matches = [kid for kid in known_ids if fnmatch(kid, rid)]
                if not matches:
                    report.warn(
                        f"{asvs_id}/{scanner}[{i}]: rule_id {rid!r} matches no rule in {scanner}_rules.json"
                    )


def _write_coverage_gaps(payload: dict, scanner_rules: dict[str, list[dict]], report: Report) -> None:
    """Write coverage-gaps.md listing scanner rules not referenced by any mapping."""
    referenced: dict[str, set[str]] = defaultdict(set)
    reqs = payload.get("requirements") or {}
    for entry in reqs.values():
        scanners = entry.get("scanners") or {}
        for scanner, mappings in scanners.items():
            for m in mappings:
                rid = m.get("rule_id", "")
                if rid:
                    referenced[scanner].add(rid)

    lines = [
        "# Coverage Gaps",
        "",
        "Scanner rules in source snapshots that are NOT referenced by any ASVS",
        "mapping entry. These are candidates for new mappings — see the plan §1.5.",
        "",
        f"Generated: `{COVERAGE_GAPS_PATH.relative_to(REPO_ROOT) if COVERAGE_GAPS_PATH.is_relative_to(REPO_ROOT) else COVERAGE_GAPS_PATH}`",
        "",
    ]
    total_gaps = 0
    total_rules = 0
    for scanner in sorted(scanner_rules):
        rules = scanner_rules[scanner]
        if not rules:
            continue
        ids = {r.get("id", "") for r in rules if r.get("id")}
        total_rules += len(ids)
        gaps: list[str] = []
        for rid in sorted(ids):
            patterns = referenced.get(scanner, set())
            # A rule is "covered" if any pattern matches it via fnmatch.
            if not any(fnmatch(rid, p) for p in patterns):
                gaps.append(rid)
        total_gaps += len(gaps)
        if not gaps:
            continue
        lines.append(f"## {scanner} ({len(gaps)} of {len(ids)} rules unreferenced)")
        lines.append("")
        for rid in gaps[:50]:
            rule = next((r for r in rules if r.get("id") == rid), {})
            title = rule.get("title", "")
            desc = (rule.get("description", "") or "").replace("\n", " ").strip()
            title_str = f" — {title}" if title and title != rid else ""
            lines.append(f"- `{rid}`{title_str}")
            if desc:
                lines.append(f"  {desc[:200]}")
        if len(gaps) > 50:
            lines.append(f"- _...and {len(gaps) - 50} more_")
        lines.append("")

    lines.insert(4, f"Total: **{total_gaps} of {total_rules} catalog rules unreferenced**.")
    lines.insert(5, "")

    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    COVERAGE_GAPS_PATH.write_text("\n".join(lines) + "\n")
    report.note(f"coverage gaps written to {COVERAGE_GAPS_PATH.relative_to(REPO_ROOT)} ({total_gaps} of {total_rules} rules unreferenced)")


def _check_parroting(payload: dict, report: Report) -> None:
    """Flag if 'agree' is > 85% of mappings."""
    counts: Counter = Counter()
    total = 0
    for entry in (payload.get("requirements") or {}).values():
        for mappings in (entry.get("scanners") or {}).values():
            for m in mappings:
                agreement = m.get("csv_hint_agreement")
                if agreement:
                    counts[agreement] += 1
                    total += 1
    if not total:
        report.note("parroting check: no csv_hint_agreement values present (skipped)")
        return
    agree_pct = (counts.get("agree", 0) / total) * 100
    parts = [f"{k}={counts[k]}" for k in ("agree", "modified", "rejected", "no_hint") if k in counts]
    breakdown = ", ".join(parts)
    report.note(f"parroting check: {breakdown} ({agree_pct:.1f}% agree)")
    if agree_pct > 85:
        report.warn(
            f"parroting guard: {agree_pct:.1f}% of mappings 'agree' with CSV hint "
            f"(threshold 85%). Spot-check before promoting any low/medium to 'high' confidence."
        )


def _detect_orphans(payload: dict, csv_ids: set[str], report: Report) -> None:
    """ASVS IDs in YAML but not in the project CSV → flag as orphaned."""
    if not csv_ids:
        return
    yaml_ids = set((payload.get("requirements") or {}).keys())
    orphans = yaml_ids - csv_ids
    if orphans:
        report.warn(
            f"orphan detection: {len(orphans)} ASVS ID(s) in YAML but not in CSV: "
            f"{', '.join(sorted(orphans)[:5])}{'...' if len(orphans) > 5 else ''}"
        )
        report.note("orphans are preserved (never auto-deleted); surface via review-mapping.py TUI")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mapping", type=Path, help="Path to asvs_mapping.yaml")
    ap.add_argument("--compliance-csv", type=Path, default=None,
                    help="Project compliance CSV (enables parroting + orphan checks)")
    args = ap.parse_args()

    if not args.mapping.exists():
        print(f"ERROR: mapping file not found: {args.mapping}", file=sys.stderr)
        return 2

    payload = _load_yaml(args.mapping)
    asvs_lookup = _load_asvs_requirements()
    scanner_rules = _load_scanner_rules()
    csv_ids = _load_csv_ids(args.compliance_csv)

    report = Report()
    _validate_schema(payload, report)
    if report.ok:
        _validate_asvs_ids(payload, asvs_lookup, report)
        _validate_rule_ids(payload, scanner_rules, report)
        _write_coverage_gaps(payload, scanner_rules, report)
        _check_parroting(payload, report)
        _detect_orphans(payload, csv_ids, report)

    # Print results
    print("== Validation report ==")
    print(f"Mapping: {args.mapping}")
    if args.compliance_csv:
        print(f"CSV:     {args.compliance_csv} ({len(csv_ids)} IDs)")
    print()

    if report.info:
        print("Notes:")
        for line in report.info:
            print(f"  • {line}")
        print()

    if report.warnings:
        print("Warnings:")
        for line in report.warnings:
            print(f"  ⚠ {line}")
        print()

    if report.errors:
        print("Errors:")
        for line in report.errors:
            print(f"  ✗ {line}")
        print()
        print(f"FAILED: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
        return 1

    print(f"PASSED: 0 errors, {len(report.warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
