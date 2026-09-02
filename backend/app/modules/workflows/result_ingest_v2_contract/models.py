"""Workflow errors for the disabled v2 result-ingest contract."""

from __future__ import annotations


class EnvelopeValidationError(ValueError):
    """Canonical parts violate a frozen cross-part invariant."""


__all__ = ["EnvelopeValidationError"]
