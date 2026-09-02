"""Public API for explicit immutable GitHub account linking."""

from .models import (
    GithubAccountLinkDecision,
    GithubAccountLinkError,
    GithubIdentityCollisionError,
    LinkGithubAccountCommand,
    UserAlreadyLinkedError,
)
from .ports import GithubAccountLinkRepositoryPort
from .service import link_github_account

__all__ = [
    "GithubAccountLinkDecision",
    "GithubAccountLinkError",
    "GithubAccountLinkRepositoryPort",
    "GithubIdentityCollisionError",
    "LinkGithubAccountCommand",
    "UserAlreadyLinkedError",
    "link_github_account",
]
