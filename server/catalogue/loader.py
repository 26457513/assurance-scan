"""Load + validate v3 FR catalogues.

v3 is a clean break from v2 — no migration. The catalogue is a list of
FRs, each with an inline `tests` array. No more `required_evidence`,
no more mapping pack, no more TBTs.

The catalogue is re-read at the start of every scan. Each load creates
(or reuses) an immutable `catalogue_snapshots` row.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema


log = logging.getLogger(__name__)


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "data" / "schemas"
FR_CATALOG_V3_SCHEMA_PATH = SCHEMA_DIR / "fr-catalog.v3.schema.json"


@dataclass(frozen=True)
class LoadedCatalogue:
    """Result of loading a v3 catalogue file."""

    doc: dict[str, Any]                # the validated v3 doc
    path: Path
    project_path: str                  # the host path of the project being scanned
    content_hash: str                  # sha256:...
    generated_at: dt.datetime


def load_catalogue(path: Path, project_path: str) -> LoadedCatalogue:
    """Load and validate a v3 FR catalogue."""
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)

    if doc.get("schema_version") != 3:
        raise ValueError(
            f"catalogue at {path} has schema_version={doc.get('schema_version')!r}; "
            f"v3 requires schema_version=3"
        )

    _validate(doc, FR_CATALOG_V3_SCHEMA_PATH)

    return LoadedCatalogue(
        doc=doc,
        path=path,
        project_path=project_path,
        content_hash=_sha256_json(doc),
        generated_at=dt.datetime.now(dt.timezone.utc),
    )


def _validate(doc: dict[str, Any], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=doc, schema=schema)


def _sha256_json(doc: dict[str, Any]) -> str:
    body = json.dumps(doc, sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(body).hexdigest()}"
