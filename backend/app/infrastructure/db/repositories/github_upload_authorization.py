"""Race-safe persistence adapter for GitHub upload repository authorization."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    GithubAppInstallation,
    GithubInstallationRepository,
    Project,
)
from app.modules.atomic.access.github_repository_reconciliation import (
    GithubRepositorySnapshot,
)
from app.modules.atomic.access.github_upload_authorization import GithubUploadCandidate
from app.modules.atomic.provenance.repository_identity import normalize_github_repository_key


class SqlAlchemyGithubUploadAuthorizationRepository:
    """Recheck active scope while persisting the latest authoritative metadata."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_active(self, github_repository_id: int) -> GithubUploadCandidate | None:
        row = (
            await self.session.execute(self._active_statement(github_repository_id))
        ).one_or_none()
        if row is None:
            await self.session.rollback()
            return None
        repository, installation, project = row
        candidate = GithubUploadCandidate(
            github_installation_id=repository.github_installation_id,
            github_repository_id=repository.github_repository_id,
            github_owner_id=installation.github_owner_id,
            project_id=project.id,
        )
        await self.session.rollback()
        return candidate

    async def confirm(
        self,
        candidate: GithubUploadCandidate,
        snapshot: GithubRepositorySnapshot,
        *,
        verified_at: dt.datetime,
    ) -> int | None:
        if self.session.in_transaction():
            await self.session.rollback()
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))
        statement = self._active_statement(candidate.github_repository_id)
        if self.session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            await self.session.rollback()
            return None
        repository, installation, project = row
        if (
            repository.github_installation_id != candidate.github_installation_id
            or project.id != candidate.project_id
            or installation.github_owner_id != candidate.github_owner_id
            or snapshot.github_repository_id != candidate.github_repository_id
            or snapshot.github_owner_id != candidate.github_owner_id
            or snapshot.archived
            or snapshot.disabled
        ):
            await self.session.rollback()
            return None
        repository.repository_full_name = snapshot.full_name
        repository.github_owner_id = snapshot.github_owner_id
        repository.default_branch = snapshot.default_branch
        repository.visibility = snapshot.visibility.value
        repository.archived = snapshot.archived
        repository.disabled = snapshot.disabled
        repository.repository_verified_at = verified_at
        repository.updated_at = verified_at
        project.github_repo = snapshot.full_name
        project.github_repo_key = normalize_github_repository_key(snapshot.full_name)
        project.github_repository_id = snapshot.github_repository_id
        project.default_scan_ref = f"refs/heads/{snapshot.default_branch}"
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            return None
        return project.id

    @staticmethod
    def _active_statement(github_repository_id: int):
        return (
            select(GithubInstallationRepository, GithubAppInstallation, Project)
            .join(
                GithubAppInstallation,
                GithubAppInstallation.github_installation_id
                == GithubInstallationRepository.github_installation_id,
            )
            .join(Project, Project.id == GithubInstallationRepository.project_id)
            .where(
                GithubInstallationRepository.github_repository_id == github_repository_id,
                GithubInstallationRepository.removed_at.is_(None),
                GithubInstallationRepository.disabled.is_(False),
                GithubInstallationRepository.archived.is_(False),
                GithubAppInstallation.suspended_at.is_(None),
                GithubAppInstallation.deleted_at.is_(None),
                Project.hidden.is_(False),
                Project.lifecycle_state == "active",
            )
        )


__all__ = ["SqlAlchemyGithubUploadAuthorizationRepository"]
