"""Current project authorization policy, extracted without feature changes."""

from __future__ import annotations

from app.modules.shared.contracts.local_scan import TOKEN_SCOPE

from .models import LocalScanProjectContext, ProjectAction, ProjectAuthorizationDecision


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


def authorize_local_scan_upload(
    context: LocalScanProjectContext,
) -> ProjectAuthorizationDecision:
    """Apply the locked v1 upload rule without framework or database coupling.

    This Assurance Scan release is deliberately single-tenant: every active
    user with an upload-scoped token can target every visible registered
    project. Unknown and hidden projects remain indistinguishable to callers.
    """
    if not context.user_active:
        return ProjectAuthorizationDecision(False, "the submitting user is disabled")
    if TOKEN_SCOPE not in context.token_scopes:
        return ProjectAuthorizationDecision(False, "the token lacks the scan-upload scope")
    if not context.project_registered or context.project_hidden:
        return ProjectAuthorizationDecision(False, "the project is not available for upload")
    return ProjectAuthorizationDecision(
        True,
        "upload_scan is allowed by the version-one single-tenant project policy",
    )
