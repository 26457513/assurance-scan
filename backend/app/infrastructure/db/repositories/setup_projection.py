"""Entitlement-first SQLAlchemy projection for the version-two Setup UI."""

from __future__ import annotations

import base64
import datetime as dt
import json
import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    ApiToken,
    GithubAccount,
    GithubAppInstallation,
    GithubInstallationRepository,
    IngestAttempt,
    Project,
    ProjectMembership,
    Run,
)
from app.modules.atomic.access.setup_state.models import (
    AcceptedReadiness,
    NoScanReadiness,
    RejectedReadiness,
    SetupGithubIdentity,
    SetupInstallation,
    SetupLocalRun,
    SetupMachineToken,
    SetupReadiness,
    SetupRepository,
    SetupRepositoryPage,
    SetupRepositoryPermission,
    SetupTokenStatus,
)
from app.modules.workflows.setup_bootstrap import SetupProjectionMaterial


_CURSOR_VERSION = 1
_SAFE_REASON = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_MEMBERSHIP_SOURCE = "github_app"
_GITHUB_INSTALLATION_SETTINGS = "https://github.com/settings/installations"


class SetupCursorError(ValueError):
    """A Setup pagination cursor is malformed or belongs to another listing."""


class SqlAlchemySetupProjectionRepository:
    """Read Setup evidence only through the current user's GitHub grants."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_bootstrap(
        self,
        *,
        user_id: int,
        selected_repository_id: int | None,
        installations_cursor: str | None,
        now: dt.datetime,
    ) -> SetupProjectionMaterial:
        now = _aware(now)
        identity, credential_stale = await self._identity(user_id, now)
        tokens = await self._tokens(user_id, now)
        if identity is None:
            return SetupProjectionMaterial(
                identity=None,
                installations=(),
                installations_next_cursor=None,
                selected_repository=None,
                selected_installation=None,
                suspended_installation=None,
                last_repository=None,
                access_stale=False,
                retry_after_seconds=None,
                approval_request_url=None,
                actions_readiness=NoScanReadiness(),
                machine_tokens=tokens,
                latest_local_run=None,
            )

        selected = (
            await self._entitled_repository(user_id, selected_repository_id, now)
            if selected_repository_id is not None
            else None
        )
        selected_installation = (
            await self._installation_for_repository(selected.github_installation_id, user_id, now)
            if selected is not None
            else None
        )
        installations, next_cursor = await self._installations(
            user_id,
            identity.github_user_id,
            installations_cursor,
            now,
        )
        suspended = await self._suspended_installation(
            user_id,
            selected_repository_id=selected_repository_id,
        )
        last_repository = None
        if selected_repository_id is not None and selected is None:
            last_repository = await self._last_repository(user_id, selected_repository_id)
        has_expired_entitlement = await self._has_expired_entitlement(user_id, now)
        selection_stale = selected_repository_id is not None and selected is None and last_repository is not None
        access_stale = credential_stale or selection_stale or (not installations and has_expired_entitlement)
        actions_readiness = (
            await self._actions_readiness(selected.project_id, selected.full_name, now)
            if selected is not None
            else NoScanReadiness()
        )
        latest_local_run = (
            await self._latest_local_run(user_id, selected.project_id)
            if selected is not None
            else None
        )
        return SetupProjectionMaterial(
            identity=identity,
            installations=installations,
            installations_next_cursor=next_cursor,
            selected_repository=selected,
            selected_installation=selected_installation,
            suspended_installation=suspended,
            last_repository=last_repository,
            access_stale=access_stale,
            retry_after_seconds=60 if access_stale else None,
            approval_request_url=None,
            actions_readiness=actions_readiness,
            machine_tokens=tokens,
            latest_local_run=latest_local_run,
        )

    async def search_repositories(
        self,
        *,
        user_id: int,
        github_installation_id: int,
        query: str,
        cursor: str | None,
        limit: int,
        now: dt.datetime,
    ) -> SetupRepositoryPage:
        now = _aware(now)
        cursor_name, cursor_id = _decode_repository_cursor(cursor)
        name_key = func.lower(GithubInstallationRepository.repository_full_name)
        statement = (
            select(ProjectMembership.permission, GithubInstallationRepository, Project)
            .select_from(ProjectMembership)
            .join(Project, Project.id == ProjectMembership.project_id)
            .join(
                GithubInstallationRepository,
                GithubInstallationRepository.project_id == Project.id,
            )
            .join(
                GithubAppInstallation,
                GithubAppInstallation.github_installation_id
                == GithubInstallationRepository.github_installation_id,
            )
            .where(
                *_active_entitlement_predicates(user_id, now),
                GithubInstallationRepository.github_installation_id == github_installation_id,
            )
        )
        normalized_query = query.strip().casefold()
        if normalized_query:
            escaped = normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(name_key.like(f"%{escaped}%", escape="\\"))
        if cursor_name is not None and cursor_id is not None:
            statement = statement.where(
                or_(
                    name_key > cursor_name,
                    and_(
                        name_key == cursor_name,
                        GithubInstallationRepository.github_repository_id > cursor_id,
                    ),
                )
            )
        statement = statement.order_by(
            name_key,
            GithubInstallationRepository.github_repository_id,
        ).limit(limit + 1)
        rows = list((await self.session.execute(statement)).all())
        has_more = len(rows) > limit
        visible = rows[:limit]
        repositories = tuple(_repository(permission, repository, project) for permission, repository, project in visible)
        next_cursor = None
        if has_more and repositories:
            last = repositories[-1]
            next_cursor = _encode_cursor("repository", [last.full_name.casefold(), last.github_repository_id])
        return SetupRepositoryPage(repositories=repositories, next_cursor=next_cursor)

    async def _identity(self, user_id: int, now: dt.datetime) -> tuple[SetupGithubIdentity | None, bool]:
        row = (
            await self.session.execute(
                select(GithubAccount).where(
                    GithubAccount.user_id == user_id,
                    GithubAccount.github_user_id.isnot(None),
                    GithubAccount.disconnected_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if row is None or row.github_user_id is None or not row.login_at_last_verify:
            return None, False
        expires_at = _aware_or_none(row.token_expires_at)
        identity = SetupGithubIdentity(
            github_user_id=row.github_user_id,
            login=row.login_at_last_verify,
            avatar_url=None,
        )
        return identity, expires_at is not None and expires_at <= now

    async def _tokens(self, user_id: int, now: dt.datetime) -> tuple[SetupMachineToken, ...]:
        rows = (
            (
                await self.session.execute(
                    select(ApiToken)
                    .where(ApiToken.user_id == user_id)
                    .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
                )
            )
            .scalars()
            .all()
        )
        return tuple(
            SetupMachineToken(
                id=row.id,
                label=row.label,
                status=(
                    SetupTokenStatus.REVOKED
                    if row.revoked_at is not None
                    else SetupTokenStatus.EXPIRED
                    if _aware(row.expires_at) <= now
                    else SetupTokenStatus.ACTIVE
                ),
                created_at=_aware(row.created_at),
                expires_at=_aware(row.expires_at),
                last_used_at=_aware_or_none(row.last_used_at),
            )
            for row in rows
        )

    async def _installations(
        self,
        user_id: int,
        github_user_id: int,
        cursor: str | None,
        now: dt.datetime,
    ) -> tuple[tuple[SetupInstallation, ...], str | None]:
        after_id = _decode_installation_cursor(cursor)
        entitled = (
            select(
                GithubAppInstallation.github_installation_id.label("installation_id"),
                GithubAppInstallation.github_owner_id,
                GithubAppInstallation.owner_login_at_last_verify,
                GithubAppInstallation.account_type,
                GithubAppInstallation.repository_selection,
                func.count(GithubInstallationRepository.github_repository_id).label("enabled_count"),
            )
            .select_from(ProjectMembership)
            .join(Project, Project.id == ProjectMembership.project_id)
            .join(
                GithubInstallationRepository,
                GithubInstallationRepository.project_id == Project.id,
            )
            .join(
                GithubAppInstallation,
                GithubAppInstallation.github_installation_id
                == GithubInstallationRepository.github_installation_id,
            )
            .where(*_active_entitlement_predicates(user_id, now))
            .group_by(
                GithubAppInstallation.github_installation_id,
                GithubAppInstallation.github_owner_id,
                GithubAppInstallation.owner_login_at_last_verify,
                GithubAppInstallation.account_type,
                GithubAppInstallation.repository_selection,
            )
        )
        # A personal installation can safely be attributed by immutable owner
        # identity even when it currently exposes no repositories. Organisation
        # installations require an entitlement row and are never inferred.
        personal_empty = (
            select(
                GithubAppInstallation.github_installation_id.label("installation_id"),
                GithubAppInstallation.github_owner_id,
                GithubAppInstallation.owner_login_at_last_verify,
                GithubAppInstallation.account_type,
                GithubAppInstallation.repository_selection,
                func.count(GithubInstallationRepository.github_repository_id).label("enabled_count"),
            )
            .select_from(GithubAppInstallation)
            .outerjoin(
                GithubInstallationRepository,
                and_(
                    GithubInstallationRepository.github_installation_id
                    == GithubAppInstallation.github_installation_id,
                    GithubInstallationRepository.removed_at.is_(None),
                    GithubInstallationRepository.disabled.is_(False),
                    GithubInstallationRepository.archived.is_(False),
                ),
            )
            .where(
                GithubAppInstallation.github_owner_id == github_user_id,
                GithubAppInstallation.account_type == "user",
                GithubAppInstallation.suspended_at.is_(None),
                GithubAppInstallation.deleted_at.is_(None),
            )
            .group_by(
                GithubAppInstallation.github_installation_id,
                GithubAppInstallation.github_owner_id,
                GithubAppInstallation.owner_login_at_last_verify,
                GithubAppInstallation.account_type,
                GithubAppInstallation.repository_selection,
            )
            .having(func.count(GithubInstallationRepository.github_repository_id) == 0)
        )
        combined = entitled.union(personal_empty).subquery()
        statement = select(combined)
        if after_id is not None:
            statement = statement.where(combined.c.installation_id > after_id)
        statement = statement.order_by(combined.c.installation_id).limit(11)
        rows = list((await self.session.execute(statement)).all())
        has_more = len(rows) > 10
        visible = rows[:10]
        installations = tuple(
            SetupInstallation(
                github_installation_id=int(row.installation_id),
                github_owner_id=int(row.github_owner_id),
                owner_login=str(row.owner_login_at_last_verify),
                account_type="User" if row.account_type == "user" else "Organization",
                repository_selection=str(row.repository_selection),
                enabled_repository_count=int(row.enabled_count),
                manage_url=f"{_GITHUB_INSTALLATION_SETTINGS}/{int(row.installation_id)}",
            )
            for row in visible
        )
        next_cursor = (
            _encode_cursor("installation", installations[-1].github_installation_id)
            if has_more and installations
            else None
        )
        return installations, next_cursor

    async def _entitled_repository(
        self,
        user_id: int,
        repository_id: int,
        now: dt.datetime,
    ) -> SetupRepository | None:
        row = (
            await self.session.execute(
                select(ProjectMembership.permission, GithubInstallationRepository, Project)
                .select_from(ProjectMembership)
                .join(Project, Project.id == ProjectMembership.project_id)
                .join(
                    GithubInstallationRepository,
                    GithubInstallationRepository.project_id == Project.id,
                )
                .join(
                    GithubAppInstallation,
                    GithubAppInstallation.github_installation_id
                    == GithubInstallationRepository.github_installation_id,
                )
                .where(
                    *_active_entitlement_predicates(user_id, now),
                    GithubInstallationRepository.github_repository_id == repository_id,
                )
            )
        ).one_or_none()
        return _repository(*row) if row is not None else None

    async def _installation_for_repository(
        self,
        installation_id: int,
        user_id: int,
        now: dt.datetime,
    ) -> SetupInstallation | None:
        rows, _cursor = await self._installations_for_ids(user_id, (installation_id,), now)
        return rows[0] if rows else None

    async def _installations_for_ids(
        self,
        user_id: int,
        installation_ids: Sequence[int],
        now: dt.datetime,
    ) -> tuple[tuple[SetupInstallation, ...], None]:
        rows = (
            await self.session.execute(
                select(
                    GithubAppInstallation,
                    func.count(GithubInstallationRepository.github_repository_id),
                )
                .select_from(ProjectMembership)
                .join(Project, Project.id == ProjectMembership.project_id)
                .join(
                    GithubInstallationRepository,
                    GithubInstallationRepository.project_id == Project.id,
                )
                .join(
                    GithubAppInstallation,
                    GithubAppInstallation.github_installation_id
                    == GithubInstallationRepository.github_installation_id,
                )
                .where(
                    *_active_entitlement_predicates(user_id, now),
                    GithubAppInstallation.github_installation_id.in_(installation_ids),
                )
                .group_by(GithubAppInstallation.github_installation_id)
            )
        ).all()
        return tuple(_installation(installation, count) for installation, count in rows), None

    async def _suspended_installation(
        self,
        user_id: int,
        *,
        selected_repository_id: int | None,
    ) -> SetupInstallation | None:
        statement = (
            select(GithubAppInstallation, func.count(GithubInstallationRepository.github_repository_id))
            .select_from(ProjectMembership)
            .join(Project, Project.id == ProjectMembership.project_id)
            .join(
                GithubInstallationRepository,
                GithubInstallationRepository.project_id == Project.id,
            )
            .join(
                GithubAppInstallation,
                GithubAppInstallation.github_installation_id
                == GithubInstallationRepository.github_installation_id,
            )
            .where(
                ProjectMembership.user_id == user_id,
                ProjectMembership.source == _MEMBERSHIP_SOURCE,
                GithubAppInstallation.suspended_at.isnot(None),
                GithubAppInstallation.deleted_at.is_(None),
            )
            .group_by(GithubAppInstallation.github_installation_id)
            .order_by(GithubAppInstallation.github_installation_id)
            .limit(1)
        )
        if selected_repository_id is not None:
            statement = statement.where(
                GithubInstallationRepository.github_repository_id == selected_repository_id
            )
        row = (await self.session.execute(statement)).one_or_none()
        return _installation(*row) if row is not None else None

    async def _last_repository(self, user_id: int, repository_id: int) -> SetupRepository | None:
        row = (
            await self.session.execute(
                select(ProjectMembership.permission, GithubInstallationRepository, Project)
                .select_from(ProjectMembership)
                .join(Project, Project.id == ProjectMembership.project_id)
                .join(
                    GithubInstallationRepository,
                    GithubInstallationRepository.project_id == Project.id,
                )
                .where(
                    ProjectMembership.user_id == user_id,
                    ProjectMembership.source == _MEMBERSHIP_SOURCE,
                    GithubInstallationRepository.github_repository_id == repository_id,
                )
                .order_by(ProjectMembership.verified_at.desc())
                .limit(1)
            )
        ).one_or_none()
        return _repository(*row) if row is not None else None

    async def _has_expired_entitlement(self, user_id: int, now: dt.datetime) -> bool:
        return (
            await self.session.execute(
                select(ProjectMembership.id)
                .where(
                    ProjectMembership.user_id == user_id,
                    ProjectMembership.source == _MEMBERSHIP_SOURCE,
                    ProjectMembership.expires_at.isnot(None),
                    ProjectMembership.expires_at <= now,
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None

    async def _actions_readiness(
        self,
        project_id: int,
        repository_full_name: str,
        now: dt.datetime,
    ) -> SetupReadiness:
        attempt = (
            await self.session.execute(
                select(IngestAttempt)
                .where(
                    IngestAttempt.project_id == project_id,
                    IngestAttempt.origin == "github",
                    IngestAttempt.expires_at > now,
                )
                .order_by(IngestAttempt.completed_at.desc(), IngestAttempt.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if attempt is None:
            return NoScanReadiness()
        occurred_at = _aware(attempt.completed_at)
        if attempt.outcome in {"accepted", "replayed"} and attempt.run_id:
            run = await self.session.get(Run, attempt.run_id)
            github_run_id = run.github_run_id if run is not None else None
            if github_run_id is None:
                return NoScanReadiness()
            return AcceptedReadiness(
                attempt_id=attempt.id,
                accepted_at=occurred_at,
                run_id=attempt.run_id,
                actions_url=f"https://github.com/{repository_full_name}/actions/runs/{github_run_id}",
            )
        reason = attempt.reason_code if _SAFE_REASON.fullmatch(attempt.reason_code) else "upload_rejected"
        return RejectedReadiness(
            attempt_id=attempt.id,
            attempted_at=occurred_at,
            safe_code=reason,
            correlation_id=attempt.correlation_id,
            troubleshooting_url=f"/help/uploads#{reason}",
            actions_url=None,
        )

    async def _latest_local_run(self, user_id: int, project_id: int) -> SetupLocalRun | None:
        run = (
            await self.session.execute(
                select(Run)
                .where(
                    Run.project_id == project_id,
                    Run.origin == "local",
                    Run.submitted_by_user_id == user_id,
                    Run.local_run_number.isnot(None),
                    Run.commit_sha.isnot(None),
                )
                .order_by(Run.started_at.desc(), Run.run_id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if run is None or run.local_run_number is None or run.commit_sha is None:
            return None
        return SetupLocalRun(
            run_id=run.run_id,
            display_title=run.local_machine_label or "Local scan",
            branch=run.git_branch,
            commit_sha=run.commit_sha,
            dirty=bool(run.working_tree_dirty),
            status=run.status,
            started_at=_aware(run.started_at),
        )


def _active_entitlement_predicates(user_id: int, now: dt.datetime) -> tuple[Any, ...]:
    return (
        ProjectMembership.user_id == user_id,
        ProjectMembership.source == _MEMBERSHIP_SOURCE,
        ProjectMembership.expires_at.isnot(None),
        ProjectMembership.expires_at > now,
        Project.hidden.is_(False),
        GithubInstallationRepository.removed_at.is_(None),
        GithubInstallationRepository.disabled.is_(False),
        GithubInstallationRepository.archived.is_(False),
        GithubAppInstallation.suspended_at.is_(None),
        GithubAppInstallation.deleted_at.is_(None),
    )


def _repository(permission: str, row: GithubInstallationRepository, project: Project) -> SetupRepository:
    return SetupRepository(
        github_repository_id=row.github_repository_id,
        github_installation_id=row.github_installation_id,
        project_id=project.id,
        full_name=row.repository_full_name,
        default_branch=row.default_branch,
        permission=_permission(permission),
        archived=row.archived,
    )


def _permission(value: str) -> SetupRepositoryPermission:
    if value == "view":
        return SetupRepositoryPermission.READ
    if value == "upload":
        return SetupRepositoryPermission.WRITE
    if value == "manage":
        return SetupRepositoryPermission.ADMIN
    raise ValueError("unsupported GitHub project permission")


def _installation(row: GithubAppInstallation, enabled_count: int) -> SetupInstallation:
    return SetupInstallation(
        github_installation_id=row.github_installation_id,
        github_owner_id=row.github_owner_id,
        owner_login=row.owner_login_at_last_verify,
        account_type="User" if row.account_type == "user" else "Organization",
        repository_selection=row.repository_selection,
        enabled_repository_count=int(enabled_count),
        manage_url=f"{_GITHUB_INSTALLATION_SETTINGS}/{row.github_installation_id}",
    )


def _encode_cursor(kind: str, position: object) -> str:
    raw = json.dumps(
        {"v": _CURSOR_VERSION, "kind": kind, "position": position},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str | None, kind: str) -> object | None:
    if value is None:
        return None
    if not value or len(value) > 512 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise SetupCursorError("Setup cursor is invalid")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SetupCursorError("Setup cursor is invalid") from exc
    if not isinstance(document, dict) or document.get("v") != _CURSOR_VERSION or document.get("kind") != kind:
        raise SetupCursorError("Setup cursor is invalid")
    return document.get("position")


def _decode_installation_cursor(value: str | None) -> int | None:
    position = _decode_cursor(value, "installation")
    if position is None:
        return None
    if isinstance(position, bool) or not isinstance(position, int) or position <= 0:
        raise SetupCursorError("Setup cursor is invalid")
    return position


def _decode_repository_cursor(value: str | None) -> tuple[str | None, int | None]:
    position = _decode_cursor(value, "repository")
    if position is None:
        return None, None
    if (
        not isinstance(position, list)
        or len(position) != 2
        or not isinstance(position[0], str)
        or not position[0]
        or isinstance(position[1], bool)
        or not isinstance(position[1], int)
        or position[1] <= 0
    ):
        raise SetupCursorError("Setup cursor is invalid")
    return position[0], position[1]


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _aware_or_none(value: dt.datetime | None) -> dt.datetime | None:
    return _aware(value) if value is not None else None


__all__ = ["SetupCursorError", "SqlAlchemySetupProjectionRepository"]
