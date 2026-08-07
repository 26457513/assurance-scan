"""v1 → v2 catalogue migration. Collapses TBTs into parent FRs.

Strategy per `docs/mcp-stack-plan.md` §12:

  1. TBT with a parent FR → merge required_evidence / satisfies /
     implemented_by into the parent; re-point evidence to parent; drop
     the TBT entity.
  2. TBT with no parent (orphan) → promote to a standalone FR, keeping
     its TBT-* id verbatim so evidence references don't need rewriting.

`any_of` divergence is recorded but not blocked: flattening two
`any_of` blocks into one weakens the requirement slightly (originally
both had to be satisfied independently; after merge, only one needs to
be). The migration report flags any such case for human review.
"""
from __future__ import annotations

import copy
import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any


log = logging.getLogger(__name__)


@dataclass
class MigrationReport:
    """Outcome summary for a v1→v2 migration."""

    collapsed_count: int = 0
    promoted_orphans: int = 0
    evidence_repoint_count: int = 0
    any_of_divergence: list[dict[str, Any]] = field(default_factory=list)
    migrated_doc: dict[str, Any] = field(default_factory=dict)


def migrate_v1_to_v2(v1: dict[str, Any]) -> MigrationReport:
    """Migrate a v1 catalogue (with TBTs) to a v2 catalogue (no TBTs)."""
    report = MigrationReport()

    v2 = copy.deepcopy(v1)
    v2["schema_version"] = 2
    v2.setdefault("catalogue_version", _now_iso())

    raw_frs = v2.get("frs") or []
    raw_tbts = v2.pop("tbts", []) or []

    frs_by_id = {fr["id"]: fr for fr in raw_frs}

    for tbt in raw_tbts:
        parent_id = tbt.get("parent")
        if parent_id and parent_id in frs_by_id:
            _collapse_tbt_into_parent(frs_by_id[parent_id], tbt, report)
            report.collapsed_count += 1
        else:
            _promote_orphan_to_fr(frs_by_id, tbt)
            report.promoted_orphans += 1

    v2["frs"] = list(frs_by_id.values())
    report.migrated_doc = v2
    return report


def _collapse_tbt_into_parent(
    parent_fr: dict[str, Any],
    tbt: dict[str, Any],
    report: MigrationReport,
) -> None:
    """Merge TBT fields into parent_fr in-place."""
    parent_evidence = parent_fr.setdefault("required_evidence", {})
    tbt_evidence = tbt.get("required_evidence", {}) or {}

    for key in ("all_of", "any_of", "none_of"):
        target = parent_evidence.setdefault(key, [])
        source = tbt_evidence.get(key, []) or []
        if key == "any_of" and source and target:
            # Detect divergence: any_of specs that don't overlap will
            # weaken when flattened into a single any_of.
            if not _specs_overlap(target, source):
                report.any_of_divergence.append(
                    {
                        "fr_id": parent_fr["id"],
                        "tbt_id": tbt["id"],
                        "parent_any_of": target,
                        "tbt_any_of": source,
                    }
                )
        target.extend(_dedupe_specs(source))

    parent_satisfies = parent_fr.setdefault("satisfies", [])
    for sat in tbt.get("satisfies", []) or []:
        if sat not in parent_satisfies:
            parent_satisfies.append(sat)

    parent_implemented = parent_fr.setdefault("implemented_by", [])
    for ref in tbt.get("implemented_by", []) or []:
        if ref not in parent_implemented:
            parent_implemented.append(ref)

    note = f"\n\n> Migrated from {tbt['id']}: {tbt.get('title', '(no title)')}"
    parent_fr["description"] = (parent_fr.get("description", "") + note).strip()

    log.info("collapsed %s into %s", tbt["id"], parent_fr["id"])


def _promote_orphan_to_fr(
    frs_by_id: dict[str, dict[str, Any]],
    tbt: dict[str, Any],
) -> None:
    """Orphan TBT (no parent) becomes a standalone FR with the same id."""
    new_fr = {
        "id": tbt["id"],  # TBT-* id preserved
        "title": tbt.get("title", ""),
        "description": tbt.get("description", ""),
        "implemented_by": tbt.get("implemented_by", []),
        "required_evidence": tbt.get("required_evidence", {}),
        "satisfies": tbt.get("satisfies", []),
        "depends_on": tbt.get("depends_on", []),
    }
    frs_by_id[new_fr["id"]] = new_fr
    log.info("promoted orphan %s to standalone FR", tbt["id"])


def _specs_overlap(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    """True if any spec in `a` is also in `b` (by value)."""
    set_a = {_spec_key(s) for s in a}
    set_b = {_spec_key(s) for s in b}
    return bool(set_a & set_b)


def _dedupe_specs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return specs with duplicates removed. Order preserved."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for spec in specs:
        key = _spec_key(spec)
        if key in seen:
            continue
        seen.add(key)
        out.append(spec)
    return out


def _spec_key(spec: dict[str, Any]) -> str:
    """Stable string identity for an evidence spec. Used for deduping."""
    parts = [str(spec.get("type", ""))]
    for k in ("source_kind", "rule_id", "name_pattern", "format", "expected_result"):
        parts.append(f"{k}={spec.get(k, '')}")
    return "|".join(parts)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
