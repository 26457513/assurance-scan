"""Browser-managed scan-upload token endpoints."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_roles import get_current_user
from app.config import account_identity_is_ready
from app.infrastructure.db.models import (
    ApiToken,
    GithubAppInstallation,
    GithubAccount,
    GithubInstallationRepository,
    Project,
    ProjectMembership,
    User,
)
from app.infrastructure.db.repositories.api_tokens import (
    SecureScanTokenRandom,
    SqlAlchemyScanTokenRepository,
    SystemScanTokenClock,
)
from app.modules.atomic.access.browser_csrf import (
    CSRF_COOKIE_NAME,
    mint_csrf_token,
    validate_csrf_request,
)
from app.modules.atomic.access.scan_token import (
    CreateScanTokenCommand,
    ScanTokenActiveLimitError,
    ScanTokenCreationRateLimitError,
    ScanTokenLabelConflictError,
    ScanTokenRecord,
    ScanTokenValidationError,
    create_scan_token,
)


router = APIRouter(prefix="/users/me/scan-tokens", tags=["scan-tokens"])
_CSRF_HEADER = "x-csrf-token"
_CSRF_MAX_AGE_SECONDS = 60 * 60


@dataclass(frozen=True)
class BrowserScanTokenUser:
    """Minimal authenticated browser identity needed by these routes."""

    user_id: int
    github_user_id: int


class CreateScanTokenBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: str
    expires_in_days: Literal[30, 90, 180] = 90


async def require_github_scan_token_user(
    request: Request,
    session: AsyncSession = SessionDep,
    user: User | None = Depends(get_current_user),
) -> BrowserScanTokenUser:
    """Require an enabled user authenticated by a GitHub server session."""
    settings = request.app.state.settings
    if not account_identity_is_ready(settings):
        raise HTTPException(status_code=401, detail="GitHub sign-in is required")
    if user is None:
        raise HTTPException(status_code=401, detail="GitHub sign-in is required")
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="account is disabled")
    github_user_id = (
        await session.execute(
            select(GithubAccount.github_user_id).where(
                GithubAccount.user_id == user.id,
                GithubAccount.disconnected_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if github_user_id is None:
        raise HTTPException(status_code=401, detail="GitHub sign-in is required")
    identity = BrowserScanTokenUser(user_id=user.id, github_user_id=github_user_id)
    # Leave the adapter a clean transaction so it can serialize creation.
    await session.rollback()
    return identity


@router.get("")
async def list_scan_tokens(
    request: Request,
    user: BrowserScanTokenUser = Depends(require_github_scan_token_user),
    session: AsyncSession = SessionDep,
) -> JSONResponse:
    """List the caller's token audits and mint a signed CSRF token."""
    settings = request.app.state.settings
    csrf_token = mint_csrf_token(
        user_key=str(user.user_id),
        secret=settings.session_secret,
    )
    now = SystemScanTokenClock().now()
    rows = await SqlAlchemyScanTokenRepository(session).list_for_user(user.user_id)
    creation_enabled = _creation_enabled_for_user(
        settings,
        user.github_user_id,
    ) and await _has_current_upload_entitlement(session, user.user_id, now=now)
    response = JSONResponse(
        {
            "tokens": [_audit(row, now) for row in rows],
            "csrf_token": csrf_token,
            "creation_enabled": creation_enabled,
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=_CSRF_MAX_AGE_SECONDS,
        httponly=True,
        secure=urlsplit(settings.public_base_url).scheme == "https",
        samesite="strict",
        # A host-wide path prevents a second cookie with the same name and a
        # different path from making request-cookie parsing order-dependent.
        path="/",
    )
    return response


@router.post("", status_code=201)
async def issue_scan_token(
    body: CreateScanTokenBody,
    request: Request,
    user: BrowserScanTokenUser = Depends(require_github_scan_token_user),
    session: AsyncSession = SessionDep,
) -> JSONResponse:
    """Create a token and return its plaintext exactly once."""
    settings = request.app.state.settings
    if not getattr(settings, "scan_token_creation_enabled", False):
        raise HTTPException(
            status_code=503,
            detail="Scan-token creation is disabled.",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    if not _creation_enabled_for_user(settings, user.github_user_id):
        raise HTTPException(
            status_code=403,
            detail="Scan-token creation is not enabled for this account.",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    _require_csrf(request, user)
    repository = SqlAlchemyScanTokenRepository(session)
    clock = SystemScanTokenClock()
    if not await _has_current_upload_entitlement(
        session,
        user.user_id,
        now=clock.now(),
    ):
        raise HTTPException(
            status_code=403,
            detail="Current GitHub write access to an enabled repository is required.",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    try:
        issued = await create_scan_token(
            CreateScanTokenCommand(
                user_id=user.user_id,
                label=body.label,
                expiry_days=body.expires_in_days,
            ),
            repository=repository,
            clock=clock,
            random=SecureScanTokenRandom(),
        )
    except ScanTokenCreationRateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": "3600"},
        ) from exc
    except (ScanTokenActiveLimitError, ScanTokenLabelConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ScanTokenValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(
        {
            "token": issued.plaintext_token,
            "audit": _record_audit(issued.record),
        },
        status_code=201,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
        },
    )


def _creation_enabled_for_user(settings: object, github_user_id: int) -> bool:
    if not getattr(settings, "scan_token_creation_enabled", False):
        return False
    user_allowlist: frozenset[str] = getattr(
        settings,
        "scan_token_creation_github_user_allowlist",
        frozenset(),
    )
    return not user_allowlist or github_user_id in user_allowlist


async def _has_current_upload_entitlement(
    session: AsyncSession,
    user_id: int,
    *,
    now: dt.datetime,
) -> bool:
    """Require a live GitHub App grant through an active installed repository."""
    statement = (
        select(ProjectMembership.id)
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
            ProjectMembership.source == "github_app",
            ProjectMembership.permission.in_(("upload", "manage")),
            ProjectMembership.expires_at.is_not(None),
            ProjectMembership.expires_at > now,
            Project.hidden.is_(False),
            GithubInstallationRepository.removed_at.is_(None),
            GithubInstallationRepository.disabled.is_(False),
            GithubInstallationRepository.archived.is_(False),
            GithubAppInstallation.suspended_at.is_(None),
            GithubAppInstallation.deleted_at.is_(None),
        )
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None


@router.delete("/{token_id}")
async def revoke_scan_token(
    token_id: str,
    request: Request,
    user: BrowserScanTokenUser = Depends(require_github_scan_token_user),
    session: AsyncSession = SessionDep,
) -> dict[str, str]:
    """Idempotently revoke one of the caller's tokens without enumeration."""
    _require_csrf(request, user)
    await SqlAlchemyScanTokenRepository(session).revoke_owned(
        user_id=user.user_id,
        token_id=token_id,
        now=SystemScanTokenClock().now(),
    )
    return {"status": "revoked"}


def _require_csrf(request: Request, user: BrowserScanTokenUser) -> None:
    settings = request.app.state.settings
    if not validate_csrf_request(
        cookie_token=request.cookies.get(CSRF_COOKIE_NAME),
        header_token=request.headers.get(_CSRF_HEADER),
        request_origin=request.headers.get("origin"),
        public_base_url=settings.public_base_url,
        user_key=str(user.user_id),
        secret=settings.session_secret,
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def _audit(row: ApiToken, now: dt.datetime) -> dict[str, object]:
    expires_at = _aware(row.expires_at)
    if row.revoked_at is not None:
        status = "revoked"
    elif expires_at <= now:
        status = "expired"
    else:
        status = "active"
    return {
        "id": row.id,
        "label": row.label,
        "scope": row.scope,
        "status": status,
        "created_at": _aware(row.created_at).isoformat(),
        "expires_at": expires_at.isoformat(),
        "last_used_at": _aware(row.last_used_at).isoformat() if row.last_used_at else None,
        "revoked_at": _aware(row.revoked_at).isoformat() if row.revoked_at else None,
    }


def _record_audit(record: ScanTokenRecord) -> dict[str, object]:
    return {
        "id": record.token_id,
        "label": record.label,
        "scope": record.scope,
        "status": "active",
        "created_at": record.created_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        "last_used_at": None,
        "revoked_at": None,
    }


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value


__all__ = [
    "BrowserScanTokenUser",
    "require_github_scan_token_user",
    "router",
]
