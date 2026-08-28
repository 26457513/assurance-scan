"""Git repository metadata capability."""

from .models import GitCommandPort, GitCommandResult, GitMetadataError, GitRepositoryMetadata
from .service import collect_git_metadata, normalize_github_repository
from ._adapters import SubprocessGitCommand

__all__ = [
    "GitCommandPort",
    "GitCommandResult",
    "GitMetadataError",
    "GitRepositoryMetadata",
    "SubprocessGitCommand",
    "collect_git_metadata",
    "normalize_github_repository",
]
