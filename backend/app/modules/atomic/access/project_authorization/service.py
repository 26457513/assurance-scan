"""Current project authorization policy, extracted without feature changes."""

from __future__ import annotations

from .models import ProjectAction, ProjectAuthorizationDecision


def authorize_project_action(action: ProjectAction) -> ProjectAuthorizationDecision:
    """Allow project actions after the application's existing auth boundary.

    The application currently has no per-project membership policy. Making
    that fact explicit creates the atomic extension point needed later while
    preserving today's behavior exactly. Token scopes and target-project
    authorization are intentionally deferred to the local-scan workstream.
    """
    return ProjectAuthorizationDecision(
        allowed=True,
        reason=f"{action} is allowed by the current application-wide policy",
    )
