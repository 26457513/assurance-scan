"""Refresh expiring project entitlements from GitHub's authoritative user scope."""

from __future__ import annotations

import asyncio
import datetime as dt

from app.modules.atomic.access.github_membership_projection import (
    project_membership_projections,
)
from app.modules.atomic.access.github_membership_projection.ports import (
    GithubMembershipProjectionPort,
    GithubUserEntitlementPort,
)


ENTITLEMENT_TTL = dt.timedelta(minutes=5)


async def refresh_github_app_memberships(
    *,
    user_id: int,
    now: dt.datetime,
    repository: GithubMembershipProjectionPort,
    github: GithubUserEntitlementPort,
    force: bool = False,
) -> bool:
    """Replace one user's grants atomically, failing closed on stale evidence."""
    if user_id <= 0:
        raise ValueError("user id must be positive")
    if now.tzinfo is None or now.utcoffset() is None:
        raise RuntimeError("entitlement refresh timestamp must be timezone-aware")
    if not force and await repository.is_fresh(user_id, now=now):
        return True
    token = await repository.access_token(user_id, now=now)
    if token is None:
        await repository.expire_for_user(user_id, expired_at=now)
        return False
    try:
        entitlements = await asyncio.to_thread(github.fetch, token)
    except Exception:
        await repository.expire_for_user(user_id, expired_at=now)
        return False
    project_ids = await repository.project_ids(entitlements)
    projections = project_membership_projections(
        entitlements,
        project_ids,
        verified_at=now,
        expires_at=now + ENTITLEMENT_TTL,
    )
    await repository.replace_for_user(user_id, projections, refreshed_at=now)
    return True
