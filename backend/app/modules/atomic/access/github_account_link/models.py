"""Persistence-neutral contracts for explicit immutable GitHub account linking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class GithubAccountLinkDecision(StrEnum):
    LINKED = "linked"
    IDENTITY_COLLISION = "identity_collision"
    USER_ALREADY_LINKED = "user_already_linked"


@dataclass(frozen=True)
class LinkGithubAccountCommand:
    user_id: int
    github_user_id: int
    login: str
    user_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    token_expires_at: datetime | None = None
    verified_at: datetime | None = None


class GithubAccountLinkError(ValueError):
    """Base class for expected explicit-link failures."""


class GithubIdentityCollisionError(GithubAccountLinkError):
    """The immutable GitHub identity is already attached elsewhere."""


class UserAlreadyLinkedError(GithubAccountLinkError):
    """The existing user is already attached to another GitHub identity."""
