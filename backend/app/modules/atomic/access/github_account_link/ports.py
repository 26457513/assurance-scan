"""Persistence port for explicit GitHub account linking."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import GithubAccountLinkDecision, LinkGithubAccountCommand


class GithubAccountLinkRepositoryPort(Protocol):
    async def link(self, command: LinkGithubAccountCommand, *, linked_at: datetime) -> GithubAccountLinkDecision: ...
