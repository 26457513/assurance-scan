"""Fail-closed comparison of two identity-cutover rehearsal reports."""

from __future__ import annotations

from typing import Any

from .models import IdentityCutoverError
from .service import PHASES


def compare_rehearsal_documents(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic evidence when two validated rehearsals agree."""
    first_evidence = _evidence(first)
    second_evidence = _evidence(second)
    if first_evidence != second_evidence:
        raise IdentityCutoverError("rehearsal reports do not have identical migration evidence")
    return {"status": "matched", **first_evidence}


def _evidence(document: dict[str, Any]) -> dict[str, Any]:
    required = {"preflight_checksum", "state_checksum", "counts", "completed_phases"}
    if not required.issubset(document):
        raise IdentityCutoverError("rehearsal report is missing required migration evidence")
    phases = document["completed_phases"]
    if not isinstance(phases, (list, tuple)) or tuple(phases[:4]) != PHASES[:4]:
        raise IdentityCutoverError("rehearsal report did not complete validation")
    counts = document["counts"]
    if not isinstance(counts, dict) or not all(
        isinstance(key, str) and isinstance(value, int) and value >= 0 for key, value in counts.items()
    ):
        raise IdentityCutoverError("rehearsal report has invalid counts")
    checksums = (document["preflight_checksum"], document["state_checksum"])
    if any(
        not isinstance(checksum, str)
        or len(checksum) != 64
        or any(character not in "0123456789abcdef" for character in checksum)
        for checksum in checksums
    ):
        raise IdentityCutoverError("rehearsal report has an invalid checksum")
    return {
        "preflight_checksum": checksums[0],
        "state_checksum": checksums[1],
        "counts": counts,
        "completed_phases": list(PHASES[:4]),
    }


__all__ = ["compare_rehearsal_documents"]
