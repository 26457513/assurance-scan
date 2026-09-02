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
class GithubRepositoryEntitlement:
    """One repository grant proven through a GitHub App user token."""

    github_installation_id: int
    github_repository_id: int
    permission: GithubProjectPermission


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


def project_membership_projections(
    entitlements: tuple[GithubRepositoryEntitlement, ...],
    project_ids_by_repository: dict[tuple[int, int], int],
    *,
    verified_at: datetime,
    expires_at: datetime,
) -> tuple[GithubMembershipProjection, ...]:
    """Map GitHub repository grants onto installed Assurance Scan projects."""
    if verified_at.tzinfo is None or expires_at.tzinfo is None:
        raise RuntimeError("GitHub membership timestamps must be timezone-aware")
    if expires_at <= verified_at:
        raise ValueError("GitHub membership expiry must follow verification")

    permission_rank = {
        GithubProjectPermission.VIEW: 0,
        GithubProjectPermission.UPLOAD: 1,
        GithubProjectPermission.MANAGE: 2,
    }
    by_project: dict[int, GithubProjectPermission] = {}
    seen_repositories: set[int] = set()
    for entitlement in entitlements:
        if entitlement.github_installation_id <= 0 or entitlement.github_repository_id <= 0:
            raise ValueError("GitHub entitlement identities must be positive integers")
        if entitlement.github_repository_id in seen_repositories:
            raise ValueError("GitHub entitlement repositories must be unique")
        seen_repositories.add(entitlement.github_repository_id)
        project_id = project_ids_by_repository.get(
            (
                entitlement.github_installation_id,
                entitlement.github_repository_id,
            )
        )
        if project_id is None:
            continue
        current = by_project.get(project_id)
        if current is None or permission_rank[entitlement.permission] > permission_rank[current]:
            by_project[project_id] = entitlement.permission

    return validate_membership_projection(
        tuple(
            GithubMembershipProjection(
                project_id=project_id,
                permission=permission,
                verified_at=verified_at,
                expires_at=expires_at,
            )
            for project_id, permission in sorted(by_project.items())
        )
    )
