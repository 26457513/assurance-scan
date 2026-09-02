"""Persistence boundary for authorization-time repository verification."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.modules.atomic.access.github_repository_reconciliation import (
    GithubRepositorySnapshot,
)

from .models import GithubUploadCandidate


class GithubUploadAuthorizationRepository(Protocol):
    async def load_active(self, github_repository_id: int) -> GithubUploadCandidate | None: ...

    async def confirm(
        self,
        candidate: GithubUploadCandidate,
        snapshot: GithubRepositorySnapshot,
        *,
        verified_at: datetime,
    ) -> int | None: ...


__all__ = ["GithubUploadAuthorizationRepository"]
