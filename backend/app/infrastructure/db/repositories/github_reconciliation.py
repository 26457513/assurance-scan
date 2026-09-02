"""Atomic database projection of an authoritative GitHub installation snapshot."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    GithubAppInstallation,
    GithubInstallationRepository,
    Project,
    ProjectMembership,
)
from app.modules.atomic.access.github_repository_reconciliation import (
    GithubInstallationSnapshot,
    ReconciliationResult,
    ReconciliationValidationError,
)
from app.modules.atomic.provenance.repository_identity import normalize_github_repository_key


class SqlAlchemyGithubRepositoryReconciliationRepository:
    """Replace one installation scope without inferring identity from names."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace(
        self,
        snapshot: GithubInstallationSnapshot,
        *,
        verified_at: dt.datetime,
    ) -> ReconciliationResult:
        await self._begin_write()
        try:
            result = await self._replace(snapshot, verified_at=verified_at)
            await self.session.commit()
            return result
        except Exception:
            await self.session.rollback()
            raise

    async def deactivate(
        self,
        github_installation_id: int,
        *,
        deleted_at: dt.datetime,
    ) -> ReconciliationResult:
        await self._begin_write()
        try:
            installation = await self.session.get(GithubAppInstallation, github_installation_id)
            if installation is None:
                await self.session.commit()
                return _empty_result(github_installation_id)
            if _is_stale(installation.last_reconciled_at, deleted_at):
                await self.session.commit()
                return _empty_result(github_installation_id)
            installation.deleted_at = deleted_at
            installation.last_reconciled_at = deleted_at
            installation.updated_at = deleted_at
            repositories = (
                (
                    await self.session.execute(
                        select(GithubInstallationRepository).where(
                            GithubInstallationRepository.github_installation_id == github_installation_id,
                            GithubInstallationRepository.removed_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            invalidated: set[int] = set()
            removed: list[int] = []
            for repository_row in repositories:
                repository_row.disabled = True
                repository_row.removed_at = deleted_at
                repository_row.updated_at = deleted_at
                removed.append(repository_row.github_repository_id)
                if repository_row.project_id is not None:
                    invalidated.add(repository_row.project_id)
                    project = await self.session.get(Project, repository_row.project_id)
                    if project is not None:
                        project.hidden = True
            await self._expire_memberships(invalidated, expired_at=deleted_at)
            await self.session.commit()
            return ReconciliationResult(
                installation_id=github_installation_id,
                enabled_repository_ids=(),
                disabled_repository_ids=tuple(sorted(removed)),
                removed_repository_ids=tuple(sorted(removed)),
                invalidated_project_ids=tuple(sorted(invalidated)),
            )
        except Exception:
            await self.session.rollback()
            raise

    async def suspend(
        self,
        github_installation_id: int,
        *,
        suspended_at: dt.datetime,
        verified_at: dt.datetime,
    ) -> ReconciliationResult:
        await self._begin_write()
        try:
            installation = await self.session.get(GithubAppInstallation, github_installation_id)
            if installation is None:
                raise ReconciliationValidationError(
                    "suspended installation is not yet known and must be retried"
                )
            if _is_stale(installation.last_reconciled_at, verified_at):
                await self.session.commit()
                return _empty_result(github_installation_id)
            installation.suspended_at = suspended_at
            installation.last_reconciled_at = verified_at
            installation.updated_at = verified_at
            repositories = (
                (
                    await self.session.execute(
                        select(GithubInstallationRepository).where(
                            GithubInstallationRepository.github_installation_id == github_installation_id,
                            GithubInstallationRepository.removed_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            invalidated: set[int] = set()
            disabled: list[int] = []
            for repository_row in repositories:
                repository_row.disabled = True
                repository_row.updated_at = verified_at
                disabled.append(repository_row.github_repository_id)
                if repository_row.project_id is not None:
                    invalidated.add(repository_row.project_id)
                    project = await self.session.get(Project, repository_row.project_id)
                    if project is not None:
                        project.hidden = True
            await self._expire_memberships(invalidated, expired_at=suspended_at)
            await self.session.commit()
            return ReconciliationResult(
                installation_id=github_installation_id,
                enabled_repository_ids=(),
                disabled_repository_ids=tuple(sorted(disabled)),
                removed_repository_ids=(),
                invalidated_project_ids=tuple(sorted(invalidated)),
            )
        except Exception:
            await self.session.rollback()
            raise

    async def _replace(
        self,
        snapshot: GithubInstallationSnapshot,
        *,
        verified_at: dt.datetime,
    ) -> ReconciliationResult:
        installation = await self.session.get(GithubAppInstallation, snapshot.github_installation_id)
        installation_changed = installation is None
        if installation is not None and _is_stale(installation.last_reconciled_at, verified_at):
            return _empty_result(snapshot.github_installation_id)
        if installation is not None and installation.github_owner_id != snapshot.github_owner_id:
            raise ReconciliationValidationError("installation owner identity changed and requires audited rebind")
        if installation is None:
            installation = GithubAppInstallation(
                github_installation_id=snapshot.github_installation_id,
                github_owner_id=snapshot.github_owner_id,
                owner_login_at_last_verify=snapshot.owner_login,
                account_type=snapshot.account_type.value,
                repository_selection=snapshot.repository_selection.value,
                suspended_at=snapshot.suspended_at,
                deleted_at=snapshot.deleted_at,
                repositories_etag=snapshot.repositories_etag,
                reconciliation_cursor=snapshot.reconciliation_cursor,
                last_reconciled_at=verified_at,
                created_at=verified_at,
                updated_at=verified_at,
            )
            self.session.add(installation)
        else:
            installation_changed = _installation_access_state(installation) != (
                snapshot.repository_selection.value,
                _timestamp_key(snapshot.suspended_at),
                _timestamp_key(snapshot.deleted_at),
            )
            installation.owner_login_at_last_verify = snapshot.owner_login
            installation.account_type = snapshot.account_type.value
            installation.repository_selection = snapshot.repository_selection.value
            installation.suspended_at = snapshot.suspended_at
            installation.deleted_at = snapshot.deleted_at
            installation.repositories_etag = snapshot.repositories_etag
            installation.reconciliation_cursor = snapshot.reconciliation_cursor
            installation.last_reconciled_at = verified_at
            installation.updated_at = verified_at

        existing_rows = {
            row.github_repository_id: row
            for row in (
                await self.session.execute(
                    select(GithubInstallationRepository).where(
                        GithubInstallationRepository.github_installation_id == snapshot.github_installation_id
                    )
                )
            )
            .scalars()
            .all()
        }
        incoming_ids = {item.github_repository_id for item in snapshot.repositories}
        invalidated: set[int] = set()
        enabled: list[int] = []
        disabled: list[int] = []

        for item in snapshot.repositories:
            repository_row = await self._repository_row(snapshot.github_installation_id, item.github_repository_id)
            project = await self._project(item.github_repository_id, item.full_name, verified_at)
            inactive = bool(
                snapshot.suspended_at
                or snapshot.deleted_at
                or item.disabled
                or item.github_owner_id != snapshot.github_owner_id
            )
            old_state = _repository_access_state(repository_row)
            if repository_row is None:
                repository_row = GithubInstallationRepository(
                    github_installation_id=snapshot.github_installation_id,
                    github_repository_id=item.github_repository_id,
                    project_id=project.id,
                    repository_full_name=item.full_name,
                    github_owner_id=item.github_owner_id,
                    default_branch=item.default_branch,
                    visibility=item.visibility.value,
                    archived=item.archived,
                    disabled=inactive,
                    repository_verified_at=verified_at,
                    enabled_at=verified_at,
                    removed_at=None,
                    updated_at=verified_at,
                )
                self.session.add(repository_row)
            else:
                repository_row.project_id = project.id
                repository_row.repository_full_name = item.full_name
                repository_row.github_owner_id = item.github_owner_id
                repository_row.default_branch = item.default_branch
                repository_row.visibility = item.visibility.value
                repository_row.archived = item.archived
                repository_row.disabled = inactive
                repository_row.repository_verified_at = verified_at
                repository_row.removed_at = None
                repository_row.updated_at = verified_at
            project.github_repo = item.full_name
            project.github_repo_key = normalize_github_repository_key(item.full_name)
            project.lifecycle_state = "active"
            project.hidden = inactive
            new_state = _repository_access_state(repository_row)
            if installation_changed or old_state != new_state:
                invalidated.add(project.id)
            (disabled if inactive or item.archived else enabled).append(item.github_repository_id)

        removed: list[int] = []
        for repository_id, repository_row in existing_rows.items():
            if repository_id in incoming_ids or repository_row.removed_at is not None:
                continue
            repository_row.removed_at = verified_at
            repository_row.disabled = True
            repository_row.updated_at = verified_at
            removed.append(repository_id)
            if repository_row.project_id is not None:
                invalidated.add(repository_row.project_id)
                removed_project = await self.session.get(Project, repository_row.project_id)
                if removed_project is not None:
                    removed_project.hidden = True

        await self._expire_memberships(invalidated, expired_at=verified_at)
        return ReconciliationResult(
            installation_id=snapshot.github_installation_id,
            enabled_repository_ids=tuple(sorted(enabled)),
            disabled_repository_ids=tuple(sorted(disabled)),
            removed_repository_ids=tuple(sorted(removed)),
            invalidated_project_ids=tuple(sorted(invalidated)),
        )

    async def _repository_row(self, installation_id: int, repository_id: int) -> GithubInstallationRepository | None:
        row = (
            await self.session.execute(
                select(GithubInstallationRepository).where(
                    GithubInstallationRepository.github_repository_id == repository_id
                )
            )
        ).scalar_one_or_none()
        if row is not None and row.github_installation_id != installation_id:
            raise ReconciliationValidationError(
                "repository belongs to another installation and requires audited rebind"
            )
        return row

    async def _project(self, repository_id: int, full_name: str, verified_at: dt.datetime) -> Project:
        project = (
            await self.session.execute(select(Project).where(Project.github_repository_id == repository_id))
        ).scalar_one_or_none()
        if project is not None:
            return project
        tag = f"github-{repository_id}"
        collision = (await self.session.execute(select(Project.id).where(Project.tag == tag))).scalar_one_or_none()
        if collision is not None:
            raise ReconciliationValidationError("deterministic project tag is already assigned to another identity")
        project = Project(
            tag=tag,
            github_repo=full_name,
            github_repo_key=normalize_github_repository_key(full_name),
            github_repository_id=repository_id,
            hidden=False,
            lifecycle_state="active",
            created_at=verified_at,
        )
        self.session.add(project)
        await self.session.flush()
        return project

    async def _begin_write(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))

    async def _expire_memberships(self, project_ids: set[int], *, expired_at: dt.datetime) -> None:
        if not project_ids:
            return
        await self.session.execute(
            update(ProjectMembership)
            .where(
                ProjectMembership.project_id.in_(project_ids),
                ProjectMembership.source == "github_app",
                (ProjectMembership.expires_at.is_(None)) | (ProjectMembership.expires_at > expired_at),
            )
            .values(expires_at=expired_at)
        )


def _installation_access_state(
    row: GithubAppInstallation,
) -> tuple[str, dt.datetime | None, dt.datetime | None]:
    return (
        row.repository_selection,
        _timestamp_key(row.suspended_at),
        _timestamp_key(row.deleted_at),
    )


def _repository_access_state(
    row: GithubInstallationRepository | None,
) -> tuple[int, bool, bool, bool] | None:
    if row is None:
        return None
    return (
        row.github_owner_id,
        row.archived,
        row.disabled,
        row.removed_at is not None,
    )


def _timestamp_key(value: dt.datetime | None) -> dt.datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(dt.timezone.utc).replace(tzinfo=None)


def _is_stale(last_reconciled_at: dt.datetime | None, candidate: dt.datetime) -> bool:
    previous = _timestamp_key(last_reconciled_at)
    proposed = _timestamp_key(candidate)
    return previous is not None and proposed is not None and previous > proposed


def _empty_result(github_installation_id: int) -> ReconciliationResult:
    return ReconciliationResult(
        installation_id=github_installation_id,
        enabled_repository_ids=(),
        disabled_repository_ids=(),
        removed_repository_ids=(),
        invalidated_project_ids=(),
    )


__all__ = ["SqlAlchemyGithubRepositoryReconciliationRepository"]
