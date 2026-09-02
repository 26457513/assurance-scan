"""Persistence port for one authoritative installation snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import GithubInstallationSnapshot, ReconciliationResult


class GithubRepositoryReconciliationPort(Protocol):
    async def replace(
        self,
        snapshot: GithubInstallationSnapshot,
        *,
        verified_at: datetime,
    ) -> ReconciliationResult: ...
