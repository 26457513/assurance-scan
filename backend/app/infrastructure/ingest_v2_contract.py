"""Checked-in JSON Schema adapter for the source-neutral v2 envelope."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


_SCHEMA_FILES = {
    "metadata": "scan-metadata.v2.schema.json",
    "findings": "scan-findings.v2.schema.json",
    "source_contexts": "source-contexts.v2.schema.json",
}


class CheckedInEnvelopeSchemaValidator:
    """Load and validate only the immutable in-image v2 schemas."""

    def __init__(self, schema_root: Path | None = None) -> None:
        root = schema_root or Path(__file__).resolve().parents[2] / "resources" / "schemas"
        self._validators = {
            part: Draft202012Validator(
                json.loads((root / filename).read_text(encoding="utf-8")),
                format_checker=FormatChecker(),
            )
            for part, filename in _SCHEMA_FILES.items()
        }

    def validate(self, part: str, document: Mapping[str, Any]) -> bool:
        validator = self._validators.get(part)
        return validator is not None and not any(validator.iter_errors(document))


__all__ = ["CheckedInEnvelopeSchemaValidator"]
