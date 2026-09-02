"""Feature-gated HTTP boundary for authenticated GitHub App webhooks."""

from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.api.deps import SessionDep
from app.infrastructure.db.repositories.github_webhooks import (
    SqlAlchemyGithubWebhookDeliveryRepository,
)
from app.modules.atomic.access.github_webhook import (
    GithubWebhookError,
    GithubWebhookErrorCode,
    GithubWebhookSecrets,
    WebhookClaimDecision,
    claim_github_webhook,
    verify_github_webhook,
)
from app.modules.shared.contracts.ingest_v2 import WEBHOOK_POLICY_V2


router = APIRouter(prefix="/v2/github", tags=["github-app-webhook"])
_LOGGER = logging.getLogger(__name__)
_MINIMUM_SECRET_BYTES = 32


@router.post("/webhook", status_code=202)
async def receive_github_app_webhook(request: Request, session: AsyncSession = SessionDep) -> JSONResponse:
    """Authenticate exact request bytes and durably claim one delivery."""
    settings = request.app.state.settings
    if not getattr(settings, "github_webhook_enabled", False):
        raise HTTPException(status_code=404, detail="not found")
    now = dt.datetime.now(dt.timezone.utc)
    secrets = _webhook_secrets(settings, now=now)
    raw_body = await _bounded_raw_body(request)
    try:
        verified = verify_github_webhook(
            raw_body,
            content_type=request.headers.get("content-type", ""),
            delivery_id=request.headers.get("x-github-delivery", ""),
            event=request.headers.get("x-github-event", ""),
            signature=request.headers.get("x-hub-signature-256", ""),
            secrets=secrets,
            now=now,
        )
    except GithubWebhookError as exc:
        raise _webhook_problem(exc.code) from exc
    decision = await claim_github_webhook(
        verified,
        repository=SqlAlchemyGithubWebhookDeliveryRepository(session),
        now=now,
    )
    if decision is WebhookClaimDecision.CONFLICT:
        _LOGGER.warning(
            "GitHub webhook delivery conflict delivery_id=%s event=%s",
            verified.delivery_id,
            verified.event,
        )
        raise HTTPException(status_code=409, detail="webhook delivery conflict")
    outcome = "replayed" if decision is WebhookClaimDecision.REPLAY else "accepted"
    if decision is WebhookClaimDecision.ACQUIRED and not verified.mutation_allowed:
        outcome = "acknowledged"
    return JSONResponse(status_code=202, content={"status": outcome})


async def _bounded_raw_body(request: Request) -> bytes:
    maximum = WEBHOOK_POLICY_V2.maximum_body_bytes
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid Content-Length") from exc
        if declared < 0:
            raise HTTPException(status_code=400, detail="invalid Content-Length")
        if declared > maximum:
            raise HTTPException(status_code=413, detail="webhook body is too large")
    body = bytearray()
    try:
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > maximum:
                raise HTTPException(status_code=413, detail="webhook body is too large")
    except ClientDisconnect as exc:
        raise HTTPException(status_code=400, detail="incomplete webhook body") from exc
    return bytes(body)


def _webhook_secrets(settings: object, *, now: dt.datetime) -> GithubWebhookSecrets:
    current_value = getattr(settings, "github_webhook_secret", "")
    previous_value = getattr(settings, "github_webhook_previous_secret", "")
    previous_until_value = getattr(settings, "github_webhook_previous_valid_until", "")
    if not isinstance(current_value, str) or len(current_value.encode()) < _MINIMUM_SECRET_BYTES:
        raise HTTPException(status_code=503, detail="GitHub webhook is not configured")
    if not isinstance(previous_value, str) or not isinstance(previous_until_value, str):
        raise HTTPException(status_code=503, detail="GitHub webhook is not configured")
    if bool(previous_value) != bool(previous_until_value):
        raise HTTPException(status_code=503, detail="GitHub webhook rotation is not configured")
    previous_until: dt.datetime | None = None
    if previous_until_value:
        try:
            previous_until = dt.datetime.fromisoformat(previous_until_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=503, detail="GitHub webhook rotation is not configured") from exc
        if previous_until.tzinfo is None or previous_until.utcoffset() is None:
            raise HTTPException(status_code=503, detail="GitHub webhook rotation is not configured")
        maximum_until = now + dt.timedelta(seconds=WEBHOOK_POLICY_V2.secret_overlap_seconds)
        if previous_until > maximum_until:
            raise HTTPException(status_code=503, detail="GitHub webhook rotation exceeds one hour")
    return GithubWebhookSecrets(
        current=current_value.encode(),
        previous=previous_value.encode() if previous_value else None,
        previous_valid_until=previous_until,
    )


def _webhook_problem(code: GithubWebhookErrorCode) -> HTTPException:
    if code is GithubWebhookErrorCode.BODY_TOO_LARGE:
        return HTTPException(status_code=413, detail="webhook body is too large")
    if code is GithubWebhookErrorCode.INVALID_CONTENT_TYPE:
        return HTTPException(status_code=415, detail="Content-Type must be application/json")
    if code is GithubWebhookErrorCode.INVALID_SIGNATURE:
        return HTTPException(status_code=401, detail="webhook signature is invalid")
    return HTTPException(status_code=400, detail=f"invalid webhook: {code.value}")


__all__ = ["router"]
