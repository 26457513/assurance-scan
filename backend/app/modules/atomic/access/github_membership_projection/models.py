"""Contracts for an expiring GitHub App entitlement projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class GithubProjectPermission(StrEnum):
    VIEW = "view"
    UPLOAD = "upload"
    MANAGE = "manage"


@dataclass(frozen=True)
class GithubMembershipProjection:
    project_id: int
    permission: GithubProjectPermission
    verified_at: datetime
    expires_at: datetime


def validate_membership_projection(
    rows: tuple[GithubMembershipProjection, ...],
) -> tuple[GithubMembershipProjection, ...]:
    """Reject duplicate projects and non-expiring/stale projection rows."""
    seen: set[int] = set()
    for row in rows:
        if row.project_id <= 0 or row.project_id in seen:
            raise ValueError("GitHub membership projects must be unique positive IDs")
        if row.verified_at.tzinfo is None or row.expires_at.tzinfo is None:
            raise RuntimeError("GitHub membership timestamps must be timezone-aware")
        if row.expires_at <= row.verified_at:
            raise ValueError("GitHub membership expiry must follow verification")
        seen.add(row.project_id)
    return rows
