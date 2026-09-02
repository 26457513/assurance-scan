"""Compose signed workload identity, live repository state and replay fencing."""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.modules.atomic.access.github_oidc import (
    GithubOidcClaims,
    GithubOidcReplayRepository,
    GithubRepositoryTrust,
    OidcValidationError,
    authorize_default_branch_push,
    consume_github_oidc_jti,
    validate_github_payload_metadata,
)
from app.modules.atomic.access.github_repository_reconciliation import (
    GithubRepositorySnapshot,
)
from app.modules.atomic.access.github_upload_authorization import (
    GithubUploadAuthorizationRepository,
)

from .models import GithubActionsUploadPrincipal


AuthoritativeRepositoryLoader = Callable[
    [int, str, dt.datetime], Awaitable[GithubRepositorySnapshot]
]


async def authorize_github_actions_upload(
    claims: GithubOidcClaims,
    metadata: Mapping[str, Any],
    *,
    now: dt.datetime,
    repository_loader: AuthoritativeRepositoryLoader,
    authorization_repository: GithubUploadAuthorizationRepository,
    replay_repository: GithubOidcReplayRepository,
) -> GithubActionsUploadPrincipal:
    """Authorize one project only after a live GitHub metadata verification."""
    validate_github_payload_metadata(claims, metadata)
    candidate = await authorization_repository.load_active(claims.repository_id)
    if candidate is None or candidate.github_owner_id != claims.repository_owner_id:
        raise OidcValidationError("repository_not_authorized")
    snapshot = await repository_loader(
        candidate.github_installation_id,
        claims.repository,
        now,
    )
    if (
        snapshot.github_repository_id != claims.repository_id
        or snapshot.github_owner_id != claims.repository_owner_id
        or snapshot.full_name != claims.repository
        or snapshot.archived
        or snapshot.disabled
    ):
        raise OidcValidationError("repository_not_authorized")
    authorize_default_branch_push(
        claims,
        GithubRepositoryTrust(
            repository_id=snapshot.github_repository_id,
            owner_id=snapshot.github_owner_id,
            full_name=snapshot.full_name,
            default_branch=snapshot.default_branch,
        ),
    )
    project_id = await authorization_repository.confirm(
        candidate,
        snapshot,
        verified_at=now,
    )
    if project_id is None:
        raise OidcValidationError("stale_entitlement")
    await consume_github_oidc_jti(claims, repository=replay_repository, now=now)
    return GithubActionsUploadPrincipal(
        project_id=project_id,
        github_repository_id=claims.repository_id,
        github_owner_id=claims.repository_owner_id,
        github_run_id=claims.run_id,
        github_run_attempt=claims.run_attempt,
    )


__all__ = ["AuthoritativeRepositoryLoader", "authorize_github_actions_upload"]
