"""Public API for canonical repository identity handling."""

from .models import InvalidRepositoryIdentityError, ProjectSummary
from .service import merge_github_aliases, parse_github_repository

__all__ = [
    "InvalidRepositoryIdentityError",
    "ProjectSummary",
    "merge_github_aliases",
    "parse_github_repository",
]
