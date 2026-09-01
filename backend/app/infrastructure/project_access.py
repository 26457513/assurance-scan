"""GitHub-backed project-membership synchronization and database authorization."""

from __future__ import annotations

import asyncio
import datetime as dt
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.github_poller import GitHubClient
from app.infrastructure.db.models import (
    GithubAccount,
    Project,
    ProjectMembership,
    Run,
    User,
)
from app.modules.atomic.access.project_membership import allowed_permissions
from app.modules.atomic.access.project_membership.service import ProjectPermission
from app.secrets import decrypt


ACCESS_TTL = dt.timedelta(minutes=5)
ADMIN_ROLES = frozenset(("admin", "superuser"))


@dataclass(frozen=True)
class ProjectAccessPrincipal:
    user_id: int | None
    role: str

    @property
    def sees_all_projects(self) -> bool:
        return self.role in ADMIN_ROLES or self.user_id is None


SYSTEM_PRINCIPAL = ProjectAccessPrincipal(user_id=None, role="system")
CURRENT_PROJECT_ACCESS: ContextVar[ProjectAccessPrincipal] = ContextVar(
    "current_project_access", default=SYSTEM_PRINCIPAL
)


def _github_permission(repository: dict) -> str | None:
    permissions = repository.get("permissions") or {}
    if permissions.get("admin") or permissions.get("maintain"):
        return "manage"
    if permissions.get("push"):
        return "upload"
    if permissions.get("pull") or permissions.get("triage"):
        return "view"
    return None


async def sync_github_memberships(
    session: AsyncSession,
    user: User,
    settings: Settings,
    *,
    force: bool = False,
) -> bool:
    """Replace one user's GitHub-derived grants from an authoritative repo listing."""
    now = dt.datetime.now(dt.timezone.utc)
    synced_at = user.github_access_synced_at
    if synced_at is not None and synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=dt.timezone.utc)
    if not force and synced_at is not None and now - synced_at < ACCESS_TTL:
        return True

    account = (
        await session.execute(select(GithubAccount).where(GithubAccount.email == user.email))
    ).scalar_one_or_none()
    if account is None:
        await session.execute(
            delete(ProjectMembership).where(
                ProjectMembership.user_id == user.id,
                ProjectMembership.source == "github",
            )
        )
        user.github_access_synced_at = now
        await session.commit()
        return True
    if not settings.token_encryption_key:
        return False
    token = decrypt(account.token_encrypted, settings.token_encryption_key)
    if not token:
        return False
    try:
        repositories = await asyncio.to_thread(GitHubClient(token).user_repositories)
    except Exception:
        await session.rollback()
        return False

    grants = {
        str(repository.get("full_name") or "").casefold(): _github_permission(repository)
        for repository in repositories
    }
    projects = (
        await session.execute(
            select(Project).where(
                Project.hidden.is_(False), Project.github_repo_key.is_not(None)
            )
        )
    ).scalars().all()
    await session.execute(
        delete(ProjectMembership).where(
            ProjectMembership.user_id == user.id,
            ProjectMembership.source == "github",
        )
    )
    for project in projects:
        permission = grants.get(project.github_repo_key or "")
        if permission is not None:
            session.add(
                ProjectMembership(
                    user_id=user.id,
                    project_id=project.id,
                    permission=permission,
                    source="github",
                    verified_at=now,
                )
            )
    user.github_access_synced_at = now
    await session.commit()
    return True


def project_access_clause(
    principal: ProjectAccessPrincipal,
    required: ProjectPermission = "view",
):
    if principal.sees_all_projects:
        return Project.hidden.is_(False)
    cutoff = dt.datetime.now(dt.timezone.utc) - ACCESS_TTL
    membership = ProjectMembership
    return (
        Project.hidden.is_(False)
        & exists()
        .where(
            membership.project_id == Project.id,
            membership.user_id == principal.user_id,
            membership.permission.in_(allowed_permissions(required)),
            or_(membership.source == "manual", membership.verified_at >= cutoff),
        )
    )


async def visible_project_ids(
    session: AsyncSession,
    principal: ProjectAccessPrincipal,
    required: ProjectPermission = "view",
) -> set[int] | None:
    if principal.sees_all_projects:
        return None
    return set(
        (
            await session.execute(
                select(Project.id).where(project_access_clause(principal, required))
            )
        ).scalars()
    )


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
            .where(Run.run_id == run_id, project_access_clause(principal, required))
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
    "sync_github_memberships",
    "visible_project_ids",
]
