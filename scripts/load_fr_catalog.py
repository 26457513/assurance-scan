#!/usr/bin/env python3
"""Load and validate a Functional Requirements (FR) catalog JSON file.

Validates against ``data/schemas/fr-catalog.schema.json`` (Draft 2020-12)
and performs semantic reference checks that JSON Schema can't express:

- ``parent`` references must point to an existing requirement ``id``
  in the same catalog
- ``satisfies.framework`` should match a known framework (warns on unknown)
- ``satisfies.row`` should exist in the referenced framework's snapshot
  (warns if the snapshot is bundled and the row isn't found)

Usage::

    from load_fr_catalog import load_fr_catalog
    catalog = load_fr_catalog(Path("fr-catalog.json"))
    # raises FrCatalogError on schema failure
    # raises FrCatalogWarning aggregation on semantic issues (recoverable)

CLI::

    python3 scripts/load_fr_catalog.py path/to/fr-catalog.json
    # exits 0 on success, 1 on schema error, 2 on usage error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "data" / "schemas" / "fr-catalog.schema.json"
FRAMEWORKS_DIR = REPO_ROOT / "data" / "frameworks"

# Frameworks we have bundled snapshots for. Used for cross-reference checks.
KNOWN_FRAMEWORKS = {"ASVS", "NIST-800-53", "PCI-DSS", "ISO-27001", "NIST-CSF"}


@dataclass
class FrCatalogError(Exception):
    """Raised when the catalog fails JSON Schema validation (unrecoverable)."""

    errors: list[str]

    def __str__(self) -> str:
        return f"FR catalog schema validation failed ({len(self.errors)} error(s)):\n" + "\n".join(
            f"  - {e}" for e in self.errors
        )


@dataclass
class FrCatalogWarning:
    """A recoverable issue (unknown framework, dangling reference, etc.)."""

    severity: str  # "warn" | "info"
    code: str
    message: str


@dataclass
class FrCatalog:
    """Validated FR catalog with helper accessors."""

    raw: dict[str, Any]
    project: str
    version: int
    requirements: list[dict[str, Any]]
    scope: dict[str, Any] = field(default_factory=dict)
    na_rows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[FrCatalogWarning] = field(default_factory=list)

    @property
    def requirement_ids(self) -> set[str]:
        return {r["id"] for r in self.requirements}

    def by_id(self, fr_id: str) -> dict[str, Any] | None:
        for r in self.requirements:
            if r["id"] == fr_id:
                return r
        return None


def _validate_schema(catalog: dict[str, Any]) -> list[str]:
    """Run JSON Schema validation. Returns list of error strings (empty if OK)."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return ["jsonschema package not installed — run: pip install jsonschema"]

    if not SCHEMA_PATH.exists():
        return [f"Schema file not found: {SCHEMA_PATH}"]

    schema = json.loads(SCHEMA_PATH.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(catalog), key=lambda e: list(e.absolute_path))]


def _load_framework_row_ids(framework: str) -> set[str] | None:
    """Load row IDs for a known framework. Returns None if no snapshot bundled."""
    # Try common naming variants
    candidates = [
        FRAMEWORKS_DIR / framework.lower().replace("-", "_") / "requirements.json",
        FRAMEWORKS_DIR / framework / "requirements.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text())
                rows = data.get("requirements") or data.get("entries") or []
                return {r.get("id", "") for r in rows if r.get("id")}
            except Exception:
                return None
    return None


def _semantic_checks(catalog: dict[str, Any]) -> list[FrCatalogWarning]:
    """Run reference integrity checks. Returns list of warnings (recoverable issues)."""
    warnings: list[FrCatalogWarning] = []
    requirements = catalog.get("requirements") or []
    ids = {r.get("id") for r in requirements if r.get("id")}

    # parent references must exist
    for req in requirements:
        parent = req.get("parent")
        if parent and parent not in ids:
            warnings.append(FrCatalogWarning(
                severity="warn",
                code="fr_catalog.dangling_parent",
                message=f"FR {req.get('id')}: parent '{parent}' does not match any requirement id",
            ))

    # framework references — warn on unknown, check row existence for known
    framework_cache: dict[str, set[str] | None] = {}
    for req in requirements:
        for sat in req.get("satisfies") or []:
            fw = sat.get("framework")
            row = sat.get("row")
            if not fw or not row:
                continue
            if fw not in KNOWN_FRAMEWORKS:
                warnings.append(FrCatalogWarning(
                    severity="info",
                    code="fr_catalog.unknown_framework",
                    message=f"FR {req.get('id')}: framework '{fw}' is not in known set {sorted(KNOWN_FRAMEWORKS)}",
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

    # top-level na_rows references — same framework/row checks
    for na in catalog.get("na_rows") or []:
        fw = na.get("framework")
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
        if fw not in KNOWN_FRAMEWORKS:
            warnings.append(FrCatalogWarning(
                severity="info",
                code="fr_catalog.unknown_scope_framework",
                message=f"scope: framework '{fw}' is not in known set",
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

    return FrCatalog(
        raw=raw,
        project=raw.get("project", "(unnamed)"),
        version=raw.get("version", 1),
        requirements=raw.get("requirements") or [],
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
          f"{len(catalog.requirements)} requirements, "
          f"{len(catalog.scope)} frameworks in scope, "
          f"{len(catalog.na_rows)} N/A rows")

    if catalog.warnings:
        print(f"\n{len(catalog.warnings)} warning(s):", file=sys.stderr)
        for w in catalog.warnings:
            print(f"  [{w.severity}] {w.code}: {w.message}", file=sys.stderr)
        return 0 if not args.strict else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
