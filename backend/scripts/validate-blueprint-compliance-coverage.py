#!/usr/bin/env python3
"""Validate and summarise blueprint-to-compliance mapping coverage."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:  # pragma: no cover - argparse-visible error path
        raise ValueError(f"could not read JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON in {path}")
    return data


def resolve_path(path_text: str, *, base: Path = REPO_ROOT) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    for candidate in (base / path, Path.cwd() / path):
        if candidate.exists():
            return candidate
    return base / path


def ruleset_rows(path: Path) -> set[str]:
    data = load_json(path)
    return {str(row.get("id")) for row in data.get("rows") or [] if row.get("id")}


def parse_expectations(
    raw_values: list[str],
    *,
    option_name: str = "--expect-relationship",
) -> dict[str, tuple[str, str]]:
    expectations: dict[str, tuple[str, str]] = {}
    for raw in raw_values:
        if "=" not in raw or "/" not in raw:
            raise ValueError(f"expected {option_name} KEY=relationship/strength")
        key, expected = raw.split("=", 1)
        relationship, strength = expected.split("/", 1)
        expectations[key] = (relationship, strength)
    return expectations


def build_blueprint_index(blueprint: dict[str, Any]) -> tuple[dict[str, dict], dict[str, dict], dict[str, list[str]]]:
    frs = {str(fr["id"]): fr for fr in blueprint.get("frs") or [] if fr.get("id")}
    tbts = {str(tbt["id"]): tbt for tbt in blueprint.get("tbts") or [] if tbt.get("id")}
    tbts_by_fr: dict[str, list[str]] = {fr_id: [] for fr_id in frs}
    for tbt_id, tbt in tbts.items():
        for fr_id in tbt.get("proves") or []:
            if fr_id in frs:
                tbts_by_fr.setdefault(fr_id, []).append(tbt_id)
    return frs, tbts, tbts_by_fr


def coverage_for_pack(
    *,
    pack_path: Path,
    pack: dict[str, Any],
    frs: dict[str, dict],
    tbts: dict[str, dict],
    tbts_by_fr: dict[str, list[str]],
    expectations: dict[str, tuple[str, str]],
    mapping_expectations: dict[str, tuple[str, str]],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    errors: list[str] = []
    compliance = pack.get("compliance") or {}
    ruleset = str(compliance.get("ruleset") or "")
    version = str(compliance.get("version") or "")
    source_ref = str(compliance.get("source_ref") or "")
    row_ids: set[str] = set()
    if source_ref:
        ruleset_path = resolve_path(source_ref)
        if ruleset_path.exists():
            row_ids = ruleset_rows(ruleset_path)
        else:
            errors.append(f"{pack_path}: ruleset source not found: {source_ref}")
    else:
        errors.append(f"{pack_path}: compliance.source_ref is required for row validation")

    expected = expectations.get(ruleset)
    coverage: dict[str, dict[str, Any]] = {
        fr_id: {"ruleset": ruleset, "version": version, "rows": set(), "mapping_ids": set(), "relationships": set(), "strengths": set()}
        for fr_id in frs
    }

    tbt_to_frs: dict[str, list[str]] = {}
    for fr_id, tbt_ids in tbts_by_fr.items():
        for tbt_id in tbt_ids:
            tbt_to_frs.setdefault(tbt_id, []).append(fr_id)

    for mapping in pack.get("mappings") or []:
        mapping_id = str(mapping.get("id") or "<missing-id>")
        relationship = str(mapping.get("relationship") or "")
        strength = str(mapping.get("traceability_strength") or "")
        mapping_expected = mapping_expectations.get(mapping_id, expected)
        if mapping_expected and (relationship, strength) != mapping_expected:
            errors.append(
                f"{pack_path}: {mapping_id} expected {mapping_expected[0]}/{mapping_expected[1]} "
                f"but found {relationship}/{strength}"
            )

        refs = mapping.get("blueprint_refs") or {}
        mapped_frs: set[str] = set()
        for fr_id in refs.get("fr_refs") or []:
            if fr_id not in frs:
                errors.append(f"{pack_path}: {mapping_id} references unknown blueprint FR {fr_id}")
            else:
                mapped_frs.add(fr_id)
        for tbt_id in refs.get("tbt_refs") or []:
            if tbt_id not in tbts:
                errors.append(f"{pack_path}: {mapping_id} references unknown blueprint TBT {tbt_id}")
            mapped_frs.update(tbt_to_frs.get(tbt_id, []))

        rows = mapping.get("targets", {}).get("compliance_rows") or []
        row_labels: list[str] = []
        for row in rows:
            row_ruleset = str(row.get("ruleset") or ruleset)
            row_id = str(row.get("row") or "")
            if row_ruleset != ruleset:
                errors.append(f"{pack_path}: {mapping_id} row {row_id} ruleset {row_ruleset} does not match pack ruleset {ruleset}")
            if row_ids and row_id not in row_ids:
                errors.append(f"{pack_path}: {mapping_id} references missing {ruleset} row {row_id}")
            row_labels.append(row_id)

        for fr_id in mapped_frs:
            item = coverage[fr_id]
            item["rows"].update(row_labels)
            item["mapping_ids"].add(mapping_id)
            item["relationships"].add(relationship)
            item["strengths"].add(strength)

    for fr_id, item in coverage.items():
        if not item["mapping_ids"]:
            errors.append(f"{pack_path}: blueprint FR {fr_id} has no {ruleset} mapping")
    return errors, coverage


def render_coverage_table(frs: dict[str, dict], coverages: list[dict[str, dict[str, Any]]]) -> str:
    lines = ["Blueprint FR | Regime | Rows/controls | Mappings | Relationship | Strength", "--- | --- | --- | --- | --- | ---"]
    for fr_id in sorted(frs):
        for coverage in coverages:
            item = coverage[fr_id]
            lines.append(
                " | ".join([
                    fr_id,
                    f"{item['ruleset']} {item['version']}",
                    ", ".join(sorted(item["rows"])) or "-",
                    str(len(item["mapping_ids"])),
                    ", ".join(sorted(item["relationships"])) or "-",
                    ", ".join(sorted(item["strengths"])) or "-",
                ])
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blueprint", required=True, type=Path, help="Blueprint FR catalog JSON")
    parser.add_argument("--mapping-pack", action="append", required=True, type=Path, help="Blueprint compliance mapping pack JSON. May be repeated.")
    parser.add_argument("--expect-relationship", action="append", default=[], help="Expected RULESET=relationship/strength, for example ASVS=satisfies/direct")
    parser.add_argument(
        "--expect-mapping-relationship",
        action="append",
        default=[],
        help="Per-mapping override MAPPING_ID=relationship/strength; keeps ruleset defaults strict",
    )
    parser.add_argument("--format", choices=["table", "json"], default="table")
    args = parser.parse_args()

    try:
        expectations = parse_expectations(args.expect_relationship)
        mapping_expectations = parse_expectations(
            args.expect_mapping_relationship,
            option_name="--expect-mapping-relationship",
        )
        blueprint = load_json(args.blueprint)
        frs, tbts, tbts_by_fr = build_blueprint_index(blueprint)
        errors: list[str] = []
        coverages: list[dict[str, dict[str, Any]]] = []
        for pack_path in args.mapping_pack:
            pack = load_json(pack_path)
            pack_errors, coverage = coverage_for_pack(
                pack_path=pack_path,
                pack=pack,
                frs=frs,
                tbts=tbts,
                tbts_by_fr=tbts_by_fr,
                expectations=expectations,
                mapping_expectations=mapping_expectations,
            )
            errors.extend(pack_errors)
            coverages.append(coverage)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.format == "json":
            serialisable = []
            for coverage in coverages:
                for fr_id, item in coverage.items():
                    serialisable.append({
                        "blueprint_fr": fr_id,
                        "ruleset": item["ruleset"],
                        "version": item["version"],
                        "rows": sorted(item["rows"]),
                        "mapping_count": len(item["mapping_ids"]),
                        "relationships": sorted(item["relationships"]),
                        "traceability_strengths": sorted(item["strengths"]),
                    })
            print(json.dumps({"coverage": serialisable}, indent=2))
        else:
            print(render_coverage_table(frs, coverages))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
