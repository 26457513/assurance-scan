"""Contracts for project authorization decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProjectAction = Literal["read", "create", "update", "delete"]


@dataclass(frozen=True)
class ProjectAuthorizationDecision:
    """The result of applying the current project-access policy."""

    allowed: bool
    reason: str
