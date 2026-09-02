"""Ports owned by the Setup bootstrap workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.modules.atomic.access.setup_state.models import SetupRepositoryPage

from .models import SetupProjectionMaterial


class SetupProjectionRepositoryPort(Protocol):
    async def load_bootstrap(
        self,
        *,
        user_id: int,
        selected_repository_id: int | None,
        installations_cursor: str | None,
        now: datetime,
    ) -> SetupProjectionMaterial: ...

    async def search_repositories(
        self,
        *,
        user_id: int,
        github_installation_id: int,
        query: str,
        cursor: str | None,
        limit: int,
        now: datetime,
    ) -> SetupRepositoryPage: ...


__all__ = ["SetupProjectionRepositoryPort"]
