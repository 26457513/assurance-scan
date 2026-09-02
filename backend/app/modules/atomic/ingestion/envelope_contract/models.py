"""Value objects for strict v2 JSON and envelope hashing."""

from __future__ import annotations


class CanonicalJSONError(ValueError):
    """Input is not valid in the frozen integer-only JCS profile."""


class EnvelopeHashError(ValueError):
    """Envelope parts do not satisfy the frozen hashing contract."""


__all__ = ["CanonicalJSONError", "EnvelopeHashError"]
