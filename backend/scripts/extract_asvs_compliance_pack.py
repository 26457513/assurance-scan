"""Extract ASVS rows from the security-core blueprint into a compliance pack.

One-shot script — run once, commit the result. The blueprint's FR/TBT
data stays where it is for reference; the compliance pack is the only
thing the v3 system reads at runtime.
"""
from __future__ import annotations

import json
from pathlib import Path


BLUEPRINT_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "blueprints"
    / "security-core"
    / "asvs-5.0.0"
    / "fr-catalog.blueprint.json"
)
OUTPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "compliance-packs"
    / "asvs-5.0.0.json"
)


def main() -> None:
    bp = json.loads(BLUEPRINT_PATH.read_text(encoding="utf-8"))

    # Collect every ASVS row referenced anywhere in the blueprint.
    rows_by_id: dict[str, dict] = {}

    # The `scope` block lists in-scope rows but without titles. We need
    # the titles from elsewhere — gather them from TBT `compliance` arrays
    # and FR `satisfies` arrays, plus the `metadata.asvs_title` hint on TBTs.
    for tbt in bp.get("tbts", []):
        for comp in tbt.get("compliance", []):
            if comp.get("ruleset") != "ASVS":
                continue
            row_id = comp["row"]
            if row_id in rows_by_id:
                continue
            title = (
                tbt.get("metadata", {}).get("asvs_title")
                or tbt.get("title")
                or row_id
            )
            rows_by_id[row_id] = {
                "row": row_id,
                "title": title,
                "description": tbt.get("description", ""),
                "section": _section_from_row(row_id),
            }

    # Some in-scope rows might not have TBT entries. Add them with empty titles.
    for row_id in bp.get("scope", {}).get("ASVS", {}).get("include_rows", []):
        if row_id not in rows_by_id:
            rows_by_id[row_id] = {
                "row": row_id,
                "title": row_id,
                "section": _section_from_row(row_id),
            }

    rows = sorted(rows_by_id.values(), key=lambda r: r["row"])

    pack = {
        "schema_version": 1,
        "framework": "ASVS",
        "version": "5.0.0",
        "source": {
            "url": "https://owasp.org/www-project-application-security-verification-standard/",
            "license": "CC-BY-SA-4.0",
            "retrieved_at": bp.get("generated_at", "2026-07-13T00:00:00Z"),
        },
        "rows": rows,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(pack, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {len(rows)} ASVS rows to {OUTPUT_PATH}")


def _section_from_row(row_id: str) -> str:
    """'v5.0.0-7.1.1' -> 'V7.1'."""
    parts = row_id.split("-", 1)
    if len(parts) != 2:
        return row_id
    section_parts = parts[1].split(".")
    if len(section_parts) < 2:
        return parts[1]
    return "V" + ".".join(section_parts[:2])


if __name__ == "__main__":
    main()
