"""Public contracts for GitHub App installation setup state."""

from .models import (
    ConsumedGithubInstallationState,
    GithubInstallationStateMaterial,
    GithubInstallationStateValidationError,
)
from .service import (
    ALLOWED_INSTALLATION_RETURN_PATHS,
    INSTALLATION_STATE_TTL,
    digest_installation_state,
    issue_github_installation_state,
)

__all__ = [
    "ALLOWED_INSTALLATION_RETURN_PATHS",
    "ConsumedGithubInstallationState",
    "GithubInstallationStateMaterial",
    "GithubInstallationStateValidationError",
    "INSTALLATION_STATE_TTL",
    "digest_installation_state",
    "issue_github_installation_state",
]
