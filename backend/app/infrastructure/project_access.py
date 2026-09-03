"""GitHub-backed project-membership synchronization and database authorization."""

from __future__ import annotations

import datetime as dt
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.infrastructure.db.models import (
    Project,
    ProjectMembership,
    Run,
)
from app.infrastructure.db.repositories.github_memberships import (
    SqlAlchemyGithubMembershipProjectionRepository,
)
from app.infrastructure.github_app_api import GithubAppUserEntitlementClient
from app.infrastructure.github_user_credentials import usable_github_access_token
from app.modules.workflows.github_app_access import refresh_github_app_memberships
from app.modules.atomic.access.project_membership import allowed_permissions
from app.modules.atomic.access.project_membership.service import ProjectPermission


ACCESS_TTL = dt.timedelta(minutes=5)
@dataclass(frozen=True)
class ProjectAccessPrincipal:
    user_id: int | None
    role: str

    @property
    def sees_all_projects(self) -> bool:
        """Whether this is the explicit internal system principal.

        Human administration roles never bypass repository entitlement.
        """
        return self.user_id is None


SYSTEM_PRINCIPAL = ProjectAccessPrincipal(user_id=None, role="system")
CURRENT_PROJECT_ACCESS: ContextVar[ProjectAccessPrincipal] = ContextVar(
    "current_project_access", default=SYSTEM_PRINCIPAL
)


async def sync_github_app_memberships(
    session: AsyncSession,
    user_id: int,
    settings: Settings,
    *,
    force: bool = False,
) -> bool:
    """Refresh installation-scoped GitHub App grants for one linked user."""
    if not settings.github_app_access_enabled:
        return False
    now = dt.datetime.now(dt.timezone.utc)
    if await usable_github_access_token(
        session,
        user_id=user_id,
        settings=settings,
        now=now,
    ) is None:
        return False
    repository = SqlAlchemyGithubMembershipProjectionRepository(
        session,
        encryption_key=settings.token_encryption_key,
    )
    return await refresh_github_app_memberships(
        user_id=user_id,
        now=now,
        repository=repository,
        github=GithubAppUserEntitlementClient(),
        force=force,
    )


def project_access_clause(
    principal: ProjectAccessPrincipal,
    required: ProjectPermission = "view",
):
    if principal.sees_all_projects:
        return Project.hidden.is_(False)
    now = dt.datetime.now(dt.timezone.utc)
    membership = ProjectMembership
    return Project.hidden.is_(False) & exists().where(
        membership.project_id == Project.id,
        membership.user_id == principal.user_id,
        membership.permission.in_(allowed_permissions(required)),
        (membership.source == "github_app") & (membership.expires_at > now),
    )


def run_visibility_clause(principal: ProjectAccessPrincipal):
    """Restrict local runs to their submitting user at the SQL boundary."""
    if principal.user_id is None:
        return true()
    return or_(
        Run.origin != "local",
        Run.submitted_by_user_id == principal.user_id,
    )


def run_access_clause(
    principal: ProjectAccessPrincipal,
    required: ProjectPermission = "view",
):
    """Combine current project entitlement with private-local ownership."""
    return project_access_clause(principal, required) & run_visibility_clause(principal)


def shared_github_run_clause():
    """Select the only origin allowed to contribute to shared aggregates."""
    return Run.origin == "github-actions"


async def visible_project_ids(
    session: AsyncSession,
    principal: ProjectAccessPrincipal,
    required: ProjectPermission = "view",
) -> set[int] | None:
    if principal.sees_all_projects:
        return None
    return set((await session.execute(select(Project.id).where(project_access_clause(principal, required)))).scalars())


async def require_project(
    session: AsyncSession,
    principal: ProjectAccessPrincipal,
    project_id: int,
    required: ProjectPermission = "view",
) -> Project | None:
    return (
        await session.execute(
            select(Project).where(
                Project.id == project_id,
                project_access_clause(principal, required),
            )
        )
    ).scalar_one_or_none()


async def require_run(
    session: AsyncSession,
    principal: ProjectAccessPrincipal,
    run_id: str,
    required: ProjectPermission = "view",
) -> Run | None:
    return (
        await session.execute(
            select(Run)
            .join(Project, Project.id == Run.project_id)
            .where(Run.run_id == run_id, run_access_clause(principal, required))
        )
    ).scalar_one_or_none()


__all__ = [
    "ACCESS_TTL",
    "CURRENT_PROJECT_ACCESS",
    "ProjectAccessPrincipal",
    "SYSTEM_PRINCIPAL",
    "project_access_clause",
    "require_project",
    "require_run",
    "run_access_clause",
    "shared_github_run_clause",
    "run_visibility_clause",
    "sync_github_app_memberships",
    "visible_project_ids",
]
