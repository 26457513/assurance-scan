"""Ports for refreshing GitHub App-backed project memberships."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import GithubMembershipProjection, GithubRepositoryEntitlement


class GithubUserEntitlementPort(Protocol):
    def fetch(self, user_token: str) -> tuple[GithubRepositoryEntitlement, ...]: ...


class GithubMembershipProjectionPort(Protocol):
    async def is_fresh(self, user_id: int, *, now: datetime) -> bool: ...

    async def access_token(self, user_id: int, *, now: datetime) -> str | None: ...

    async def project_ids(
        self,
        entitlements: tuple[GithubRepositoryEntitlement, ...],
    ) -> dict[tuple[int, int], int]: ...

    async def replace_for_user(
        self,
        user_id: int,
        rows: tuple[GithubMembershipProjection, ...],
        *,
        refreshed_at: datetime,
    ) -> None: ...

    async def expire_for_user(self, user_id: int, *, expired_at: datetime) -> None: ...
