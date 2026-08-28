"""Contracts for project authorization decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProjectAction = Literal["read", "create", "update", "delete", "upload_scan"]


@dataclass(frozen=True)
class ProjectAuthorizationDecision:
    """The result of applying the current project-access policy."""

    allowed: bool
    reason: str


@dataclass(frozen=True)
class LocalScanProjectContext:
    """Inputs to the explicit version-one single-tenant upload policy."""

    user_active: bool
    token_scopes: frozenset[str]
    project_registered: bool
    project_hidden: bool
