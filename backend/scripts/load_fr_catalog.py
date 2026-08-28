#!/usr/bin/env python3
"""Load and validate a Functional Requirements (FR) catalog JSON file.

The target catalog shape is:

- ``frs``: project-owned Functional Requirements
- ``tbts``: Test Basis records that prove one or more FRs

When the optional ``jsonschema`` package is available the loader validates
against ``data/schemas/fr-catalog.schema.json`` (Draft 2020-12). It always
performs semantic reference checks that JSON Schema can't express:

- ``parent`` references must point to an existing FR ``id``
  in the same catalog
- ``tbt.proves`` references must point to existing FR IDs
- ``satisfies.ruleset`` should match a known bundled ruleset where possible
- ``satisfies.row`` should exist in the referenced ruleset snapshot where bundled
  (warns if the snapshot is bundled and the row isn't found)

Usage::

    from load_fr_catalog import load_fr_catalog
    catalog = load_fr_catalog(Path("fr-catalog.json"))
    # raises FrCatalogError on schema/semantic failure
    # raises FrCatalogWarning aggregation on semantic issues (recoverable)

CLI::

    python3 scripts/load_fr_catalog.py path/to/fr-catalog.json
    # exits 0 on success, 1 on schema error, 2 on usage error
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "resources" / "schemas" / "fr-catalog.schema.json"
RULESETS_DIR = REPO_ROOT / "resources" / "rulesets"

# Rulesets we have bundled snapshots for, or expect to support soon. Used for
# cross-reference checks and informational warnings.
KNOWN_RULESETS = {"ASVS", "NIST-800-53", "PCI-DSS", "ISO-27001", "NIST-CSF"}

DEFAULT_OWNER_BY_CATEGORY = (
    (("auth", "access", "session", "role", "permission", "administrator"), "auth-team"),
    (("resources", "pii", "privacy", "sensitivity", "classification"), "data-security-team"),
    (("audit", "logging", "log", "trace"), "platform-security-team"),
    (("document", "storage", "corpus", "ingestion", "metadata", "source"), "document-platform-team"),
    (("ai", "agent", "prompt", "model", "ontology", "knowledge"), "ai-platform-team"),
)


class FrCatalogError(Exception):
    """Raised when the catalog fails JSON Schema validation (unrecoverable)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(self._format())

    def _format(self) -> str:
        return f"FR catalog schema validation failed ({len(self.errors)} error(s)):\n" + "\n".join(
            f"  - {e}" for e in self.errors
        )

    def __str__(self) -> str:
        return self._format()


class FrCatalogWarning:
    """A recoverable issue (unknown framework, dangling reference, etc.)."""

    def __init__(self, severity: str, code: str, message: str) -> None:
        self.severity = severity  # "warn" | "info"
        self.code = code
        self.message = message


class FrCatalog:
    """Validated FR catalog with helper accessors."""

    def __init__(self, raw: dict[str, Any], project: str, schema_version: int,
                 frs: list[dict[str, Any]],
                 tbts: list[dict[str, Any]] | None = None,
                 scope: dict[str, Any] | None = None,
                 na_rows: list[dict[str, Any]] | None = None,
                 warnings: list[FrCatalogWarning] | None = None) -> None:
        self.raw = raw
        self.project = project
        self.schema_version = schema_version
        self.frs = frs
        self.tbts = tbts or []
        self.scope = scope or {}
        self.na_rows = na_rows or []
        self.warnings = warnings or []

    @property
    def fr_ids(self) -> set[str]:
        return {r["id"] for r in self.frs}

    @property
    def tbt_ids(self) -> set[str]:
        return {t["id"] for t in self.tbts}

    def by_id(self, fr_id: str) -> dict[str, Any] | None:
        for r in self.frs:
            if r["id"] == fr_id:
                return r
        return None

    def tbt_by_id(self, tbt_id: str) -> dict[str, Any] | None:
        for tbt in self.tbts:
            if tbt["id"] == tbt_id:
                return tbt
        return None

def _validate_schema(catalog: dict[str, Any]) -> list[str]:
    """Run JSON Schema validation. Returns list of error strings (empty if OK)."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []

    if not SCHEMA_PATH.exists():
        return [f"Schema file not found: {SCHEMA_PATH}"]

    schema = json.loads(SCHEMA_PATH.read_text())
    validator_kwargs: dict[str, Any] = {}
    try:
        from referencing import Registry, Resource  # type: ignore

        schema_dir = SCHEMA_PATH.parent
        resources = []
        for path in schema_dir.glob("*.schema.json"):
            loaded = json.loads(path.read_text())
            schema_id = loaded.get("$id")
            if schema_id:
                resources.append((schema_id, Resource.from_contents(loaded)))
        validator_kwargs["registry"] = Registry().with_resources(resources)
    except Exception:
        validator_kwargs = {}
    validator = jsonschema.Draft202012Validator(schema, **validator_kwargs)
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(catalog), key=lambda e: list(e.absolute_path))]


def _load_framework_row_ids(framework: str, version: str | None = None) -> set[str] | None:
    """Load row IDs for a canonical ruleset snapshot."""
    root = RULESETS_DIR / framework.lower()
    candidates: list[Path] = []
    if version:
        candidates.append(root / f"{version}.json")
    candidates.extend(sorted(root.glob("*.json")))
    for path in candidates:
        try:
            data = json.loads(path.read_text())
            rows = data.get("rows") or []
            return {r.get("id", "") for r in rows if r.get("id")}
        except Exception:
            return None
    return None


def _default_owner_for_fr(fr: dict[str, Any]) -> str:
    text = " ".join(
        str(fr.get(key, ""))
        for key in ("category", "title", "description")
    ).lower()
    for terms, owner in DEFAULT_OWNER_BY_CATEGORY:
        if any(term in text for term in terms):
            return owner
    return "product-security-team"


def _primary_assignment_value(fr: dict[str, Any], responsibility: str = "owner") -> str:
    for assignment in fr.get("assignments") or []:
        if assignment.get("responsibility") == responsibility and assignment.get("party"):
            return str(assignment["party"])
    return ""


def _normalise_catalog(raw: dict[str, Any]) -> dict[str, Any]:
    catalog = copy.deepcopy(raw)
    for fr in catalog.get("frs") or []:
        assignments = [
            assignment
            for assignment in (fr.get("assignments") or [])
            if assignment.get("party") and assignment.get("responsibility")
        ]
        if not assignments:
            assignments = [{
                "party": _default_owner_for_fr(fr),
                "responsibility": "owner",
                "source": "derived_from_category",
            }]
        fr["assignments"] = assignments
        fr["owner"] = _primary_assignment_value(fr) or assignments[0]["party"]
    return catalog


def _semantic_checks(catalog: dict[str, Any]) -> list[FrCatalogWarning]:
    """Run reference integrity checks. Returns list of warnings (recoverable issues)."""
    warnings: list[FrCatalogWarning] = []
    frs = catalog.get("frs") or []
    tbts = catalog.get("tbts") or []
    ids = {r.get("id") for r in frs if r.get("id")}

    if not isinstance(frs, list) or not frs:
        warnings.append(FrCatalogWarning(
            severity="warn",
            code="fr_catalog.missing_frs",
            message="FR catalog must contain at least one entry in 'frs'",
        ))

    seen_fr_ids: set[str] = set()
    for fr in frs:
        fr_id = fr.get("id")
        if fr_id in seen_fr_ids:
            warnings.append(FrCatalogWarning(
                severity="warn",
                code="fr_catalog.duplicate_fr",
                message=f"FR id '{fr_id}' is duplicated",
            ))
        seen_fr_ids.add(fr_id)

    seen_tbt_ids: set[str] = set()
    for tbt in tbts:
        tbt_id = tbt.get("id")
        if tbt_id in seen_tbt_ids:
            warnings.append(FrCatalogWarning(
                severity="warn",
                code="fr_catalog.duplicate_tbt",
                message=f"TBT id '{tbt_id}' is duplicated",
            ))
        seen_tbt_ids.add(tbt_id)
        for fr_id in tbt.get("proves") or []:
            if fr_id not in ids:
                warnings.append(FrCatalogWarning(
                    severity="warn",
                    code="fr_catalog.unknown_tbt_proof_target",
                    message=f"TBT {tbt_id}: proves unknown FR '{fr_id}'",
                ))
        if not tbt.get("compliance"):
            warnings.append(FrCatalogWarning(
                severity="info",
                code="fr_catalog.tbt_without_compliance_mapping",
                message=f"TBT {tbt_id}: no compliance rows or controls are mapped",
            ))

    # parent references must exist
    for req in frs:
        parent = req.get("parent")
        if parent and parent not in ids:
            warnings.append(FrCatalogWarning(
                severity="warn",
                code="fr_catalog.dangling_parent",
                message=f"FR {req.get('id')}: parent '{parent}' does not match any requirement id",
            ))

    # ruleset references — warn on unknown, check row existence for known
    framework_cache: dict[str, set[str] | None] = {}
    for req in frs:
        for sat in req.get("satisfies") or []:
            fw = sat.get("ruleset")
            row = sat.get("row")
            if not fw or not row:
                continue
            if fw not in KNOWN_RULESETS:
                warnings.append(FrCatalogWarning(
                    severity="info",
                    code="fr_catalog.unknown_ruleset",
                    message=f"FR {req.get('id')}: ruleset '{fw}' is not in known set {sorted(KNOWN_RULESETS)}",
                ))
                continue
            if fw not in framework_cache:
                framework_cache[fw] = _load_framework_row_ids(fw)
            row_ids = framework_cache[fw]
            if row_ids is not None and row not in row_ids:
                warnings.append(FrCatalogWarning(
                    severity="warn",
                    code="fr_catalog.unknown_row",
                    message=f"FR {req.get('id')}: framework '{fw}' row '{row}' not found in bundled snapshot",
                ))

    for tbt in tbts:
        for ref in tbt.get("compliance") or []:
            fw = ref.get("ruleset")
            row = ref.get("row")
            if not fw or not row:
                continue
            if fw not in KNOWN_RULESETS:
                warnings.append(FrCatalogWarning(
                    severity="info",
                    code="fr_catalog.unknown_tbt_ruleset",
                    message=f"TBT {tbt.get('id')}: ruleset '{fw}' is not in known set {sorted(KNOWN_RULESETS)}",
                ))
                continue
            if fw not in framework_cache:
                framework_cache[fw] = _load_framework_row_ids(fw)
            row_ids = framework_cache[fw]
            if row_ids is not None and row not in row_ids:
                warnings.append(FrCatalogWarning(
                    severity="warn",
                    code="fr_catalog.unknown_tbt_row",
                    message=f"TBT {tbt.get('id')}: framework '{fw}' row '{row}' not found in bundled snapshot",
                ))

    # top-level na_rows references — same framework/row checks
    for na in catalog.get("na_rows") or []:
        fw = na.get("ruleset")
        row = na.get("row")
        if not fw or not row:
            continue
        if fw not in framework_cache:
            framework_cache[fw] = _load_framework_row_ids(fw)
        row_ids = framework_cache[fw]
        if row_ids is not None and row not in row_ids:
            warnings.append(FrCatalogWarning(
                severity="warn",
                code="fr_catalog.unknown_na_row",
                message=f"na_rows entry: framework '{fw}' row '{row}' not found in bundled snapshot",
            ))

    # scope check — known frameworks only
    for fw in (catalog.get("scope") or {}).keys():
        if fw not in KNOWN_RULESETS:
            warnings.append(FrCatalogWarning(
                severity="info",
                code="fr_catalog.unknown_scope_ruleset",
                message=f"scope: ruleset '{fw}' is not in known set",
            ))

    return warnings


def load_fr_catalog(path: Path, strict: bool = False) -> FrCatalog:
    """Load and validate an FR catalog file.

    Args:
        path: Path to fr-catalog.json
        strict: If True, raise on warnings instead of capturing them

    Raises:
        FrCatalogError: on JSON Schema validation failure
        FrCatalogWarning: when strict=True and semantic checks find issues
    """
    if not path.exists():
        raise FrCatalogError([f"FR catalog file not found: {path}"])

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise FrCatalogError([f"Invalid JSON: {exc}"]) from exc

    schema_errors = _validate_schema(raw)
    if schema_errors:
        raise FrCatalogError(schema_errors)

    warnings = _semantic_checks(raw)
    if strict and any(w.severity == "warn" for w in warnings):
        raise FrCatalogError([w.message for w in warnings if w.severity == "warn"])

    normalized = _normalise_catalog(raw)

    return FrCatalog(
        raw=normalized,
        project=raw.get("project", "(unnamed)"),
        schema_version=raw.get("schema_version", 1),
        frs=normalized.get("frs") or [],
        tbts=raw.get("tbts") or [],
        scope=raw.get("scope") or {},
        na_rows=raw.get("na_rows") or [],
        warnings=warnings,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("catalog", type=Path, help="Path to fr-catalog.json")
    ap.add_argument("--strict", action="store_true",
                    help="Treat warnings as errors (exit 1 on any warning)")
    args = ap.parse_args()

    try:
        catalog = load_fr_catalog(args.catalog, strict=args.strict)
    except FrCatalogError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {args.catalog.name} — project '{catalog.project}', "
          f"{len(catalog.frs)} FRs, "
          f"{len(catalog.tbts)} TBTs, "
          f"{len(catalog.scope)} rulesets in scope, "
          f"{len(catalog.na_rows)} N/A rows")

    if catalog.warnings:
        print(f"\n{len(catalog.warnings)} warning(s):", file=sys.stderr)
        for w in catalog.warnings:
            print(f"  [{w.severity}] {w.code}: {w.message}", file=sys.stderr)
        return 1 if args.strict and any(w.severity == "warn" for w in catalog.warnings) else 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
