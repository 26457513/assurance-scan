#!/usr/bin/env python3
"""Resolve assurance status from target FR/TBT, mapping and evidence fixtures.

This is the first deterministic resolver slice for the target assurance model.
It intentionally does not use an agent. It consumes accepted/proposed config
and observed evidence artifacts, then explains TBT, FR and compliance-row
status using the same IDs that the dashboard graph will later render.
"""
from __future__ import annotations

import argparse
import json
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from load_fr_catalog import load_fr_catalog
from load_target_artifacts import load_target_artifact


STATUS_PRECEDENCE = {
    "failed": 0,
    "missing": 1,
    "manual_review": 2,
    "compensating_control": 3,
    "waived": 4,
    "partial": 5,
    "passed": 6,
    "out_of_scope": 7,
}

EVIDENCE_TYPE_BY_TBT_TYPE = {
    "unit": "test_result",
    "integration": "test_result",
    "e2e": "test_result",
    "load": "test_result",
    "test": "test_result",
    "scanner": "scanner_result",
    "manual_review": "manual",
    "document_review": "document",
    "approval": "approval",
}

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_optional_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(errors="replace"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def default_scanner_compliance_packs(fr_catalog: dict[str, Any]) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    root = REPO_ROOT / "data" / "scanner-mappings"
    for ruleset, scope_entry in (fr_catalog.get("scope") or {}).items():
        version = str((scope_entry or {}).get("version") or "")
        ruleset_dir = root / str(ruleset).lower()
        candidates = sorted((ruleset_dir / version).glob("*.json")) if version else sorted(ruleset_dir.glob("*/*.json"))
        for path in candidates:
            data = load_optional_json(path)
            if data.get("schema_version") == 1 and data.get("mappings"):
                packs.append(data)
    return packs


def evidence_io(record: dict[str, Any]) -> dict[str, Any]:
    provenance = record.get("provenance") or {}
    return {
        "inputs": record.get("inputs") or provenance.get("input_artifacts") or [],
        "outputs": record.get("outputs") or provenance.get("output_artifacts") or record.get("raw_artifacts") or [],
        "side_effects": record.get("side_effects") or [],
        "test_actions": record.get("test_actions") or [],
    }


def resolved_evidence_record(record: dict[str, Any]) -> dict[str, Any]:
    resolved = {
        "id": record.get("id"),
        "type": record.get("type"),
        "status": evidence_status(record),
        "observed": record.get("observed", True),
        "strength": record.get("evidence_strength"),
        "source": record.get("source"),
        "source_locator": record.get("source_locator"),
    }
    resolved.update(evidence_io(record))
    return resolved


def load_scanner_compliance_packs(paths: list[Path]) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    for path in paths:
        candidates = sorted(path.rglob("*.json")) if path.is_dir() else [path]
        for candidate in candidates:
            data = load_optional_json(candidate)
            if data.get("schema_version") == 1 and data.get("mappings"):
                packs.append(data)
    return packs


def scanner_finding_field(finding: dict[str, Any], output_field: str) -> str:
    if output_field in finding:
        return str(finding.get(output_field) or "")
    folded = {str(key).lower(): value for key, value in finding.items()}
    return str(folded.get(output_field.lower()) or "")


def selector_matches_finding(selector: dict[str, Any], finding: dict[str, Any]) -> bool:
    value = str(selector.get("value") or "")
    actual = scanner_finding_field(finding, str(selector.get("output_field") or "rule_id"))
    if not value or not actual:
        return False
    selector_type = selector.get("type")
    actual_folded = actual.lower()
    value_folded = value.lower()
    if selector_type == "exact":
        return actual_folded == value_folded
    if selector_type == "prefix":
        return actual_folded.startswith(value_folded)
    if selector_type == "glob":
        return fnmatchcase(actual_folded, value_folded)
    if selector_type in {"category", "cve"}:
        return value_folded in actual_folded
    return False


def findings_for_mapping(scanner: str, mapping: dict[str, Any], scanner_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selectors = mapping.get("rule_selectors") or []
    return [
        finding for finding in scanner_findings
        if finding.get("scanner") == scanner
        and any(selector_matches_finding(selector, finding) for selector in selectors)
    ]


def evidence_status(record: dict[str, Any]) -> str:
    if record.get("observed") is False:
        return "missing"
    status = record.get("result_status") or "missing"
    if status == "not_observed":
        return "missing"
    return status


def worse_status(statuses: list[str]) -> str:
    if not statuses:
        return "missing"
    return min(statuses, key=lambda status: STATUS_PRECEDENCE.get(status, 99))


def status_reason(status: str, label: str) -> str:
    reasons = {
        "passed": f"{label} has sufficient passing evidence.",
        "failed": f"{label} has failing evidence.",
        "missing": f"{label} is missing required observed evidence.",
        "manual_review": f"{label} requires manual review before it can pass.",
        "partial": f"{label} has supporting evidence but not enough to pass.",
        "waived": f"{label} has a reviewed waiver and must not be counted as passed.",
        "compensating_control": f"{label} has a compensating control and must not be counted as passed.",
        "out_of_scope": f"{label} is out of scope for the selected profile.",
    }
    return reasons.get(status, f"{label} resolved to {status}.")


def target_key(target_type: str, ref: str = "", *, ruleset: str = "", row: str = "") -> str | None:
    if target_type == "ruleset_row":
        row_ref = row or ref
        if not ruleset and ":" in row_ref:
            ruleset, _, row_ref = row_ref.partition(":")
        return f"row:{ruleset}:{row_ref}" if ruleset and row_ref else None
    if target_type in {"tbt", "fr", "evidence", "criterion", "gate"} and ref:
        return f"{target_type}:{ref}"
    if not target_type and ref:
        if ref.startswith("TBT-"):
            return f"tbt:{ref}"
        if ref.startswith("FR-"):
            return f"fr:{ref}"
        if ":" in ref:
            ruleset, _, row_ref = ref.partition(":")
            return f"row:{ruleset}:{row_ref}" if ruleset and row_ref else None
    return None


def target_key_for_control(record: dict[str, Any]) -> str | None:
    target_ref = record.get("target_ref") or {}
    if target_ref:
        return target_key(
            target_ref.get("type", ""),
            target_ref.get("ref", ""),
            ruleset=target_ref.get("ruleset", ""),
            row=target_ref.get("row", ""),
        )
    return target_key("", record.get("target", ""))


def assurance_control_effects(assurance_instance: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    effects: dict[str, list[dict[str, Any]]] = {}
    for kind, records, status_effect in (
        ("waiver", assurance_instance.get("waivers") or [], "waived"),
        ("compensating_control", assurance_instance.get("compensating_controls") or [], "compensating_control"),
    ):
        for record in records:
            key = target_key_for_control(record)
            if not key:
                continue
            effect = {
                "id": record.get("id", ""),
                "kind": kind,
                "status_effect": record.get("status_effect") or status_effect,
                "approval_status": record.get("approval_status", "pending"),
                "reason": record.get("reason", ""),
                "scope": record.get("scope", ""),
                "approved_by": record.get("approved_by", ""),
                "approved_at": record.get("approved_at", ""),
                "signature_ref": record.get("signature_ref", ""),
                "review_due_at": record.get("review_due_at", ""),
                "expires_at": record.get("expires_at", ""),
            }
            effects.setdefault(key, []).append(effect)
    return effects


def approved_control_effect(effects: list[dict[str, Any]]) -> dict[str, Any] | None:
    approved = [
        effect for effect in effects
        if effect.get("approval_status") in {"approved", "waived"}
    ]
    if not approved:
        return None
    approved.sort(key=lambda effect: 0 if effect.get("status_effect") == "compensating_control" else 1)
    return approved[0]


def apply_control_effect(status: str, label: str, effects: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not effects:
        return status, []
    approved = approved_control_effect(effects)
    if not approved:
        pending = ", ".join(effect.get("id", "") for effect in effects if effect.get("id"))
        return status, [f"{label} has pending assurance control review: {pending}."]
    effect_status = approved.get("status_effect", status)
    reason = (
        f"{label} is covered by {approved.get('kind')} {approved.get('id')} "
        f"as {effect_status}; this is not passing evidence."
    )
    return effect_status, [reason]


def default_expected_evidence(tbt: dict[str, Any]) -> list[dict[str, Any]]:
    """Return an inferred evidence requirement when the catalog is sparse.

    Config authors should eventually provide explicit expected_evidence. Until
    then, this makes every TBT visible as an evidence obligation instead of an
    unexplained missing status.
    """
    tbt_type = tbt.get("type") or "test"
    evidence_type = EVIDENCE_TYPE_BY_TBT_TYPE.get(tbt_type, "test_result")
    strength = "manual_review" if evidence_type in {"manual", "document", "approval"} else "strong"
    source = tbt.get("runner") or tbt.get("ref") or tbt.get("id")
    return [
        {
            "type": evidence_type,
            "required": True,
            "strength": strength,
            "source": source,
            "inferred": True,
            "notes": (
                "Inferred from TBT type because the FR catalog does not yet "
                "declare explicit expected_evidence."
            ),
        }
    ]


def evidence_summary(status: str, expected: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    expected_required = [item for item in expected if item.get("required", True)]
    observed = [record for record in records if record.get("observed", True) is not False and evidence_status(record) != "missing"]
    failed = [record for record in records if evidence_status(record) == "failed"]
    return {
        "expected_count": len(expected),
        "required_count": len(expected_required),
        "observed_count": len(observed),
        "failed_count": len(failed),
        "missing_required_count": max(0, len(expected_required) - len(observed)),
        "has_observed_evidence": bool(observed),
        "explanation": status_reason(status, "This TBT"),
    }


def resolve_tbt_status(
    tbt: dict[str, Any],
    evidence_by_tbt: dict[str, list[dict[str, Any]]],
    effects_by_target: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    tbt_id = tbt["id"]
    expected = tbt.get("expected_evidence") or default_expected_evidence(tbt)
    records = evidence_by_tbt.get(tbt_id, [])
    record_statuses = [evidence_status(record) for record in records]
    effects = (effects_by_target or {}).get(f"tbt:{tbt_id}", [])

    if not records:
        status = "missing" if expected else "manual_review"
    else:
        status = worse_status(record_statuses)
        if status == "passed":
            strengths = {record.get("evidence_strength") for record in records}
            if "strong" not in strengths and any(item.get("required", True) for item in expected):
                status = "partial"
    status, control_reasons = apply_control_effect(status, tbt_id, effects)

    return {
        "id": tbt_id,
        "title": tbt.get("title", tbt_id),
        "status": status,
        "type": tbt.get("type"),
        "evidence_policy": tbt.get("evidence_policy"),
        "lifecycle_status": tbt.get("lifecycle_status"),
        "proves": tbt.get("proves", []),
        "expected_evidence": expected,
        "evidence_requirements": expected,
        "evidence": [
            resolved_evidence_record(record)
            for record in records
        ],
        "observed_evidence": [
            resolved_evidence_record(record)
            for record in records
            if record.get("observed", True) is not False and evidence_status(record) != "missing"
        ],
        "evidence_summary": evidence_summary(status, expected, records),
        "assurance_controls": effects,
        "reasons": [status_reason(status, tbt_id)] + control_reasons,
    }


def resolve_fr_status(
    fr: dict[str, Any],
    tbt_statuses: dict[str, dict[str, Any]],
    effects_by_target: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    fr_id = fr["id"]
    linked = [status for status in tbt_statuses.values() if fr_id in status.get("proves", [])]
    status = worse_status([item["status"] for item in linked])
    effects = (effects_by_target or {}).get(f"fr:{fr_id}", [])
    status, control_reasons = apply_control_effect(status, fr_id, effects)
    return {
        "id": fr_id,
        "title": fr.get("title", fr_id),
        "status": status,
        "tbts": [item["id"] for item in linked],
        "evidence_summary": {
            "tbt_count": len(linked),
            "passed": sum(1 for item in linked if item.get("status") == "passed"),
            "failed": sum(1 for item in linked if item.get("status") == "failed"),
            "partial": sum(1 for item in linked if item.get("status") == "partial"),
            "manual_review": sum(1 for item in linked if item.get("status") == "manual_review"),
            "missing": sum(1 for item in linked if item.get("status") == "missing"),
            "observed_evidence_count": sum((item.get("evidence_summary") or {}).get("observed_count", 0) for item in linked),
            "expected_evidence_count": sum((item.get("evidence_summary") or {}).get("expected_count", 0) for item in linked),
        },
        "tbt_statuses": [
            {
                "id": item["id"],
                "title": item.get("title", item["id"]),
                "type": item.get("type"),
                "status": item.get("status"),
                "evidence_policy": item.get("evidence_policy"),
                "requirements": item.get("evidence_requirements", []),
                "observed_evidence": item.get("observed_evidence", []),
                "evidence_summary": item.get("evidence_summary", {}),
                "reasons": item.get("reasons", []),
            }
            for item in linked
        ],
        "assurance_controls": effects,
        "reasons": [status_reason(status, fr_id)] + [
            f"{item['id']}: {item['status']}" for item in linked
        ] + control_reasons,
    }


def resolve_compliance_status(
    fr_catalog: dict[str, Any],
    tbt_statuses: dict[str, dict[str, Any]],
    effects_by_target: dict[str, list[dict[str, Any]]] | None = None,
    scanner_blockers_by_row: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    mappings: dict[tuple[str, str], dict[str, Any]] = {}
    fr_by_tbt = {
        tbt.get("id"): tbt.get("proves", [])
        for tbt in fr_catalog.get("tbts", []) or []
        if tbt.get("id")
    }
    for tbt in fr_catalog.get("tbts", []) or []:
        tbt_id = tbt.get("id")
        if not tbt_id:
            continue
        for row in tbt.get("compliance") or []:
            ruleset = row.get("ruleset")
            row_id = row.get("row")
            if not ruleset or not row_id:
                continue
            entry = mappings.setdefault(
                (ruleset, row_id),
                {
                    "ruleset": ruleset,
                    "row_id": row_id,
                    "fr_refs": [],
                    "tbt_refs": [],
                    "sufficiency": {
                        "required_evidence": [
                            {"type": "test_result", "minimum_strength": "strong"}
                        ]
                    },
                },
            )
            for fr_id in fr_by_tbt.get(tbt_id, []):
                if fr_id not in entry["fr_refs"]:
                    entry["fr_refs"].append(fr_id)
            if tbt_id not in entry["tbt_refs"]:
                entry["tbt_refs"].append(tbt_id)
    for mapping in mappings.values():
        linked = [
            tbt_statuses[tbt_id]
            for tbt_id in mapping.get("tbt_refs", [])
            if tbt_id in tbt_statuses
        ]
        status = worse_status([item["status"] for item in linked])
        ruleset = mapping.get("ruleset")
        row_id = mapping.get("row_id")
        scanner_blockers = (scanner_blockers_by_row or {}).get(f"row:{ruleset}:{row_id}", [])
        if scanner_blockers:
            status = "failed"
        effects = (effects_by_target or {}).get(f"row:{ruleset}:{row_id}", [])
        status, control_reasons = apply_control_effect(status, f"{ruleset}:{row_id}", effects)
        scanner_reasons = [
            (
                f"Direct scanner evidence {blocker.get('id')} failed for "
                f"{ruleset}:{row_id}: {blocker.get('source_locator') or blocker.get('source') or 'scanner result'}."
            )
            for blocker in scanner_blockers
        ]
        rows.append(
            {
                "id": f"{ruleset}:{row_id}",
                "ruleset": ruleset,
                "row_id": row_id,
                "status": status,
                "fr_refs": mapping.get("fr_refs", []),
                "tbt_refs": mapping.get("tbt_refs", []),
                "sufficiency": mapping.get("sufficiency", {}),
                "assurance_controls": effects,
                "scanner_blockers": scanner_blockers,
                "reasons": [status_reason(status, f"{ruleset}:{row_id}")] + [
                    f"{item['id']}: {item['status']}" for item in linked
                ] + scanner_reasons + control_reasons,
            }
        )
    return rows


def scanner_blockers_by_compliance_row(evidence_bundle: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    blockers: dict[str, list[dict[str, Any]]] = {}
    for record in evidence_bundle.get("evidence", []) or []:
        if record.get("type") != "scanner_result" or evidence_status(record) != "failed":
            continue
        row_refs = list(record.get("ruleset_refs") or [])
        for mapping_ref in record.get("mapping_refs") or []:
            if mapping_ref.get("ruleset") and mapping_ref.get("row"):
                row_refs.append({"ruleset": mapping_ref.get("ruleset"), "row": mapping_ref.get("row")})
        for row_ref in row_refs:
            ruleset = row_ref.get("ruleset")
            row = row_ref.get("row")
            if not ruleset or not row:
                continue
            key = f"row:{ruleset}:{row}"
            blocker = {
                "id": record.get("id", ""),
                "type": record.get("type", ""),
                "status": evidence_status(record),
                "strength": record.get("evidence_strength", ""),
                "tool": record.get("tool", ""),
                "source": record.get("source", ""),
                "source_locator": record.get("source_locator", ""),
                "normalized_finding": record.get("normalized_finding", {}),
                "mapping_refs": record.get("mapping_refs", []),
            }
            blockers.setdefault(key, []).append(blocker)
    return blockers


def scanner_mapping_blockers_by_compliance_row(
    scanner_findings: list[dict[str, Any]],
    scanner_compliance_packs: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    blockers: dict[str, list[dict[str, Any]]] = {}
    for pack in scanner_compliance_packs:
        scanner = str(pack.get("scanner") or "")
        for mapping in pack.get("mappings") or []:
            if mapping.get("review_status") != "accepted":
                continue
            if mapping.get("mapping_level") != "compliance_row":
                continue
            if mapping.get("traceability_strength") != "direct":
                continue
            matched_findings = findings_for_mapping(scanner, mapping, scanner_findings)
            if not matched_findings:
                continue
            for row_ref in (mapping.get("targets") or {}).get("compliance_rows") or []:
                ruleset = row_ref.get("ruleset")
                row = row_ref.get("row")
                if not ruleset or not row:
                    continue
                key = f"row:{ruleset}:{row}"
                for finding in matched_findings[:20]:
                    blocker = {
                        "id": f"{scanner}:{mapping.get('id')}:{finding.get('rule_id') or finding.get('id') or finding.get('ruleId') or finding.get('RuleID') or 'finding'}",
                        "type": "scanner_result",
                        "status": "failed",
                        "strength": "strong" if mapping.get("assurance_effect") == "blocking_if_finding" else "supporting",
                        "tool": scanner,
                        "mapping_id": mapping.get("id", ""),
                        "assurance_effect": mapping.get("assurance_effect", ""),
                        "traceability_strength": mapping.get("traceability_strength", ""),
                        "confidence": mapping.get("confidence", ""),
                        "source": f"reports/{scanner}",
                        "source_locator": finding.get("location", ""),
                        "normalized_finding": {
                            "scanner": scanner,
                            "rule_id": finding.get("rule_id") or finding.get("ruleId") or finding.get("RuleID") or finding.get("id") or "",
                            "location": finding.get("location", ""),
                            "message": finding.get("message", ""),
                            "path": finding.get("path", ""),
                        },
                    }
                    blockers.setdefault(key, []).append(blocker)
    return blockers


def merge_blockers(*sources: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for source in sources:
        for key, blockers in source.items():
            for blocker in blockers:
                marker = (key, str(blocker.get("id") or json.dumps(blocker, sort_keys=True, default=str)))
                if marker in seen:
                    continue
                seen.add(marker)
                merged.setdefault(key, []).append(blocker)
    return merged


def resolve(args: argparse.Namespace) -> dict[str, Any]:
    fr_catalog = load_fr_catalog(args.fr_catalog).raw
    evidence_bundle = load_target_artifact(args.evidence_bundle, "evidence_bundle").raw
    assurance_instance = {}
    if getattr(args, "assurance_instance", None):
        assurance_instance = load_target_artifact(args.assurance_instance, "assurance_instance").raw
    effects_by_target = assurance_control_effects(assurance_instance)
    scanner_findings = list(getattr(args, "scanner_findings", None) or [])
    scanner_compliance_packs = list(getattr(args, "scanner_compliance_packs", None) or [])
    scanner_mapping_pack_paths = list(getattr(args, "scanner_compliance_mapping_pack", None) or [])
    if scanner_mapping_pack_paths:
        scanner_compliance_packs.extend(load_scanner_compliance_packs([Path(path) for path in scanner_mapping_pack_paths]))
    if not scanner_compliance_packs:
        scanner_compliance_packs = default_scanner_compliance_packs(fr_catalog)
    scanner_blockers = merge_blockers(
        scanner_blockers_by_compliance_row(evidence_bundle),
        scanner_mapping_blockers_by_compliance_row(scanner_findings, scanner_compliance_packs),
    )

    evidence_by_tbt: dict[str, list[dict[str, Any]]] = {}
    for record in evidence_bundle.get("evidence", []):
        evidence_by_tbt.setdefault(record.get("produced_by"), []).append(record)

    tbt_statuses = {
        tbt["id"]: resolve_tbt_status(tbt, evidence_by_tbt, effects_by_target)
        for tbt in fr_catalog.get("tbts", [])
    }
    fr_statuses = {
        fr["id"]: resolve_fr_status(fr, tbt_statuses, effects_by_target)
        for fr in fr_catalog.get("frs", [])
    }
    compliance_rows = resolve_compliance_status(fr_catalog, tbt_statuses, effects_by_target, scanner_blockers)

    return {
        "schema_version": 1,
        "project": fr_catalog.get("project"),
        "inputs": {
            "fr_catalog": str(args.fr_catalog),
            "evidence_bundle": str(args.evidence_bundle),
            "assurance_instance": str(getattr(args, "assurance_instance", "") or ""),
            "scanner_compliance_mapping_packs": [
                str(path) for path in scanner_mapping_pack_paths
            ],
        },
        "tbts": list(tbt_statuses.values()),
        "frs": list(fr_statuses.values()),
        "compliance_rows": compliance_rows,
        "assurance_controls": [
            effect
            for effects in effects_by_target.values()
            for effect in effects
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path("data/fixtures/target-schemas")
    parser.add_argument("--fr-catalog", type=Path, default=base / "fr-catalog.example.json")
    parser.add_argument("--evidence-bundle", type=Path, default=base / "evidence-bundle.example.json")
    parser.add_argument("--assurance-instance", type=Path)
    parser.add_argument("--scanner-compliance-mapping-pack", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = resolve(args)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n")
        print(f"assurance-status: written to {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
