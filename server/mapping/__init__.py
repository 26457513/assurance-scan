"""Mapping artifact loader.

Reads + validates a `fr-compliance-mapping.json` file. Lives alongside
the FR catalogue as a separate artifact so the catalogue stays pure
(what the project does) and the mapping is independently editable
(which compliance rows the project addresses).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from server.catalogue.loader import _sha256_json


log = logging.getLogger(__name__)


SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "schemas"
    / "fr-compliance-mapping.schema.json"
)


@dataclass(frozen=True)
class LoadedMapping:
    """Result of loading a mapping file."""

    doc: dict[str, Any]
    path: Path
    project_path: str
    content_hash: str
    loaded_at: dt.datetime

    @property
    def mappings(self) -> list[dict[str, Any]]:
        return self.doc.get("mappings", [])


def load_mapping(path: Path, project_path: str) -> LoadedMapping:
    """Load and validate a mapping file."""
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    _validate(doc)
    return LoadedMapping(
        doc=doc,
        path=path,
        project_path=project_path,
        content_hash=_sha256_json(doc),
        loaded_at=dt.datetime.now(dt.timezone.utc),
    )


def load_mapping_from_dict(doc: dict[str, Any], project_path: str) -> LoadedMapping:
    """Validate a mapping from an in-memory dict (no file needed)."""
    _validate(doc)
    return LoadedMapping(
        doc=doc,
        path=Path("(inline)"),
        project_path=project_path,
        content_hash=_sha256_json(doc),
        loaded_at=dt.datetime.now(dt.timezone.utc),
    )


def _validate(doc: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=doc, schema=schema)


__all__ = ["LoadedMapping", "load_mapping", "load_mapping_from_dict"]
