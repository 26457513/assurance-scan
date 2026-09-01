"""Framework-free authorization rules used by project workflows."""

from __future__ import annotations

from app.modules.shared.contracts.local_scan import TOKEN_SCOPE

from .models import LocalScanProjectContext, ProjectAction, ProjectAuthorizationDecision


def authorize_project_action(action: ProjectAction) -> ProjectAuthorizationDecision:
    """Authorize an internal action after its outer access boundary.

    Browser and MCP entry points resolve membership before invoking internal
    workflows. This helper represents that already-authorized system boundary;
    local token uploads use ``authorize_local_scan_upload`` below because they
    carry their own account, scope and project inputs.
    """
    return ProjectAuthorizationDecision(
        allowed=True,
        reason=f"{action} passed the outer project-access boundary",
    )


def authorize_local_scan_upload(
    context: LocalScanProjectContext,
) -> ProjectAuthorizationDecision:
    """Apply project-scoped upload policy without framework or database coupling."""
    if not context.user_active:
        return ProjectAuthorizationDecision(False, "the submitting user is disabled")
    if TOKEN_SCOPE not in context.token_scopes:
        return ProjectAuthorizationDecision(False, "the token lacks the scan-upload scope")
    if not context.project_registered or context.project_hidden:
        return ProjectAuthorizationDecision(False, "the project is not available for upload")
    if not context.user_can_upload:
        return ProjectAuthorizationDecision(False, "the user cannot upload to this project")
    return ProjectAuthorizationDecision(
        True,
        "upload_scan is allowed by project membership",
    )
