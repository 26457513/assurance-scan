"""Reusable bearer authentication dependency for local-ingest routes."""

from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.infrastructure.db.repositories.api_tokens import (
    SqlAlchemyScanTokenRepository,
    SystemScanTokenClock,
)
from app.modules.atomic.access.scan_token import (
    ScanTokenDecision,
    ScanTokenPrincipal,
    authenticate_scan_token,
)
from app.modules.atomic.access.auth_failure_limiter import AuthenticationFailureLimiter


def _selector_bucket(plaintext: str) -> str:
    prefix, separator, _secret = plaintext.partition(".")
    return prefix if separator and prefix.startswith("asu_v1_") else "malformed"


async def require_scan_token_principal(
    request: Request,
    session: AsyncSession = SessionDep,
) -> ScanTokenPrincipal:
    """Authenticate a scan bearer token and return its atomic principal."""
    authorization = request.headers.get("authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    plaintext = credential.strip() if separator and scheme.casefold() == "bearer" else ""
    repository = SqlAlchemyScanTokenRepository(session)
    clock = SystemScanTokenClock()
    result = await authenticate_scan_token(
        plaintext,
        repository=repository,
        clock=clock,
    )
    if result.decision is ScanTokenDecision.INSUFFICIENT_SCOPE:
        raise HTTPException(status_code=403, detail="insufficient token scope")
    if not result.authenticated or result.principal is None:
        limiter = getattr(request.app.state, "scan_token_failure_limiter", None)
        if limiter is None:
            limiter = AuthenticationFailureLimiter()
            request.app.state.scan_token_failure_limiter = limiter
        origin = request.client.host if request.client is not None else "unknown"
        rate = await limiter.record_failure(
            origin=origin,
            selector=_selector_bucket(plaintext),
        )
        if not rate.allowed:
            raise HTTPException(
                status_code=429,
                detail="authentication rate limited",
                headers={"Retry-After": str(rate.retry_after_seconds or 1)},
            )
        raise HTTPException(
            status_code=401,
            detail="invalid bearer credential",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await repository.touch_last_used(result.principal.token_id, now=clock.now())
    return result.principal


__all__ = ["require_scan_token_principal"]
