"""Inputs to the private-local run visibility policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunVisibilityContext:
    """Identity and provenance needed to decide whether one run is visible."""

    principal_user_id: int | None
    origin: str
    submitted_by_user_id: int | None
