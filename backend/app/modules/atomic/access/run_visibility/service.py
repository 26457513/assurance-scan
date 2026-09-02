"""Pure policy for keeping local scan results private to their uploader."""

from __future__ import annotations

from .models import RunVisibilityContext


def can_view_run(context: RunVisibilityContext) -> bool:
    """Return whether the principal may see a run after project authorization.

    ``None`` is reserved for the explicit internal system principal. Human
    principals, regardless of application role, see local runs only when they
    submitted them.
    """
    if context.principal_user_id is None:
        return True
    if context.origin != "local":
        return True
    return context.submitted_by_user_id == context.principal_user_id


__all__ = ["can_view_run"]
