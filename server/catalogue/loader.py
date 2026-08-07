"""Read, validate, and snapshot FR catalogues + mapping packs.

The catalogue lives in the project repo as `fr-catalog.json` (default) and
is re-read at the start of each scan. Each load creates (or reuses) an
immutable `catalogue_snapshots` row.

v1 catalogues (with TBTs) are auto-migrated to v2 (collapse TBTs into
parent FRs) on first load. The migrated v2 doc is written next to the
original so the user can review and commit it.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from server.catalogue.migrate_v1 import migrate_v1_to_v2


log = logging.getLogger(__name__)


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "data" / "schemas"
FR_CATALOG_V2_SCHEMA_PATH = SCHEMA_DIR / "fr-catalog.v2.schema.json"
MAPPING_PACK_V2_SCHEMA_PATH = SCHEMA_DIR / "evidence-mapping-pack.v2.schema.json"


@dataclass(frozen=True)
class LoadedCatalogue:
    """Result of loading a catalogue file."""

    doc: dict[str, Any]                # the validated v2 doc
    path: Path
    project_path: str                  # the host path of the project being scanned
    content_hash: str                  # sha256:...
    generated_at: dt.datetime


@dataclass(frozen=True)
class LoadedMappingPack:
    """Result of loading a mapping pack file."""

    doc: dict[str, Any]
    path: Path | None
    mappings: list[dict[str, Any]]     # the `mappings` array


def load_catalogue(path: Path, project_path: str) -> LoadedCatalogue:
    """Load and validate an FR catalogue. Auto-migrates v1 to v2."""
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)

    if doc.get("schema_version") == 1:
        log.info("catalogue is v1, migrating to v2 path=%s", path)
        report = migrate_v1_to_v2(doc)
        doc = report.migrated_doc
        _write_v2_next_to_v1(path, doc)
        log.info(
            "v1→v2 migration collapsed=%d promoted_orphans=%d any_of_divergence=%d",
            report.collapsed_count,
            report.promoted_orphans,
            len(report.any_of_divergence),
        )

    _validate(doc, FR_CATALOG_V2_SCHEMA_PATH)
    return LoadedCatalogue(
        doc=doc,
        path=path,
        project_path=project_path,
        content_hash=_sha256_json(doc),
        generated_at=dt.datetime.now(dt.timezone.utc),
    )


def load_mapping_pack(path: Path | None) -> LoadedMappingPack:
    """Load an optional evidence-mapping pack. Returns empty if path is None."""
    if path is None:
        return LoadedMappingPack(doc={"schema_version": 2, "mappings": []}, path=None, mappings=[])
    path = Path(path)
    if not path.exists():
        log.warning("mapping pack path does not exist: %s", path)
        return LoadedMappingPack(doc={"schema_version": 2, "mappings": []}, path=path, mappings=[])

    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    _validate(doc, MAPPING_PACK_V2_SCHEMA_PATH)
    return LoadedMappingPack(
        doc=doc,
        path=path,
        mappings=doc.get("mappings", []),
    )


def _validate(doc: dict[str, Any], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=doc, schema=schema)


def _sha256_json(doc: dict[str, Any]) -> str:
    import hashlib
    body = json.dumps(doc, sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def _write_v2_next_to_v1(v1_path: Path, v2_doc: dict[str, Any]) -> None:
    """Write a v2 catalogue file alongside the v1 so the user can review/commit it."""
    v2_path = v1_path.with_suffix(".v2.json")
    if v2_path.exists():
        return
    v2_path.write_text(json.dumps(v2_doc, indent=2, sort_keys=True), encoding="utf-8")
    log.info("wrote v2 catalogue next to v1: %s", v2_path)
