"""Explicit-link decision mapping with no email or login identity inference."""

from __future__ import annotations

from datetime import datetime

from .models import (
    GithubAccountLinkDecision,
    GithubIdentityCollisionError,
    LinkGithubAccountCommand,
    UserAlreadyLinkedError,
)
from .ports import GithubAccountLinkRepositoryPort


async def link_github_account(
    command: LinkGithubAccountCommand,
    *,
    linked_at: datetime,
    repository: GithubAccountLinkRepositoryPort,
) -> None:
    """Attach a verified numeric GitHub ID or fail closed on either collision."""
    if command.user_id <= 0 or command.github_user_id <= 0:
        raise ValueError("user identities must be positive integers")
    if not command.login or len(command.login) > 128:
        raise ValueError("GitHub login must contain 1 to 128 characters")
    if not command.user_token:
        raise ValueError("GitHub user token is required")
    if linked_at.tzinfo is None or linked_at.utcoffset() is None:
        raise RuntimeError("link timestamp must be timezone-aware")
    decision = await repository.link(command, linked_at=linked_at)
    if decision is GithubAccountLinkDecision.LINKED:
        return
    if decision is GithubAccountLinkDecision.IDENTITY_COLLISION:
        raise GithubIdentityCollisionError("GitHub identity is already linked")
    if decision is GithubAccountLinkDecision.USER_ALREADY_LINKED:
        raise UserAlreadyLinkedError("user is already linked to another GitHub identity")
    raise RuntimeError(f"unsupported GitHub account link decision: {decision!r}")
