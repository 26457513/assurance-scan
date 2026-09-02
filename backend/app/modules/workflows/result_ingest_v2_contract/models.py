"""Workflow errors for the disabled v2 result-ingest contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


class EnvelopeValidationError(ValueError):
    """Canonical parts violate a frozen cross-part invariant."""

    def __init__(self, message: str, *, code: str = "artifact_mismatch") -> None:
        super().__init__(message)
        self.code = code


class EnvelopeSchemaValidator(Protocol):
    def validate(self, part: str, document: Mapping[str, Any]) -> bool: ...


@dataclass(frozen=True)
class ValidatedEnvelopeV2:
    """Strictly parsed documents plus stable canonical persistence bytes."""

    metadata: Mapping[str, Any]
    findings: Mapping[str, Any]
    source_contexts: Mapping[str, Any]
    sarif: Mapping[str, Any] | None
    sbom: Mapping[str, Any] | None
    payload_hash: str
    canonical_parts: Mapping[str, bytes] = field(repr=False)


__all__ = ["EnvelopeSchemaValidator", "EnvelopeValidationError", "ValidatedEnvelopeV2"]
