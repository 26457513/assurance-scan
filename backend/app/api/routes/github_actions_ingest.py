"""Feature-gated v2 HTTP boundary for GitHub Actions push ingestion."""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any, Protocol, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.multipart_ingest import read_bounded_multipart
from app.api.problem_details import IngestProblem, problem_response
from app.infrastructure.github_app_api import GithubAppApiError
from app.infrastructure.github_oidc import GithubOidcInfrastructureError, GithubOidcJwksClient
from app.infrastructure.ingest_v2_contract import CheckedInEnvelopeSchemaValidator
from app.modules.atomic.access.github_oidc import (
    GithubOidcClaims,
    OidcValidationError,
    validate_github_payload_metadata,
)
from app.modules.atomic.ingestion.operational_signals import IngestRequestSignal, render_request_signal
from app.modules.shared.contracts.ingest_v2 import (
    ENVELOPE_LIMITS_V2,
    PART_MEDIA_TYPES,
    PROBLEM_POLICIES_V2,
    REQUIRED_PARTS,
)
from app.modules.workflows.github_actions_authentication import GithubActionsUploadPrincipal
from app.modules.workflows.github_oidc_ingest import (
    GithubIngestCommand,
    GithubIngestError,
    GithubIngestOutcome,
    GithubIngestResult,
)
from app.modules.workflows.result_ingest_v2_contract import (
    EnvelopeValidationError,
    build_validated_envelope_v2,
)


_JWKS = GithubOidcJwksClient()
_PART_LIMITS = {
    "metadata": ENVELOPE_LIMITS_V2.metadata_bytes,
    "findings": ENVELOPE_LIMITS_V2.findings_bytes,
    "source_contexts": ENVELOPE_LIMITS_V2.source_contexts_bytes,
    "sarif": ENVELOPE_LIMITS_V2.sarif_bytes,
    "sbom": ENVELOPE_LIMITS_V2.sbom_bytes,
}
_POLICIES = {policy.code: policy for policy in PROBLEM_POLICIES_V2}
_LOGGER = logging.getLogger(__name__)


class GithubActionsRequestAuthenticator(Protocol):
    async def authenticate(self, token: str, *, now: dt.datetime) -> GithubOidcClaims: ...

    async def authorize(
        self,
        claims: GithubOidcClaims,
        *,
        now: dt.datetime,
    ) -> GithubActionsUploadPrincipal: ...


class GithubActionsIngestWorkflow(Protocol):
    async def ingest(self, command: GithubIngestCommand) -> GithubIngestResult: ...


class GithubActionsIngestRoute(APIRoute):
    """Render every expected or unexpected failure without reflecting input."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            request.state.github_ingest_started = time.monotonic()
            request.state.correlation_id = str(uuid.uuid4())
            try:
                return await original(request)
            except IngestProblem as exc:
                _log_rejection(request, status=exc.status, code=exc.code)
                return problem_response(request, exc)
            except OidcValidationError as exc:
                problem = _oidc_problem(exc.code)
                _log_rejection(request, status=problem.status, code=problem.code)
                return problem_response(request, problem)
            except EnvelopeValidationError as exc:
                problem = _problem(exc.code)
                _log_rejection(request, status=problem.status, code=problem.code)
                return problem_response(request, problem)
            except GithubIngestError as exc:
                _log_rejection(request, status=exc.status, code=exc.code)
                return problem_response(
                    request,
                    IngestProblem(
                        status=exc.status,
                        code=exc.code,
                        title=exc.title,
                        detail=exc.detail,
                        retryable=exc.retryable,
                        headers=(
                            {"Retry-After": str(exc.retry_after_seconds)}
                            if exc.retry_after_seconds is not None
                            else None
                        ),
                    ),
                )
            except (GithubAppApiError, GithubOidcInfrastructureError):
                problem = _problem("github_verification_failed")
                _log_rejection(request, status=problem.status, code=problem.code)
                return problem_response(request, problem)
            except Exception:
                problem = _problem("internal_persistence_failed")
                _log_rejection(request, status=problem.status, code=problem.code)
                return problem_response(request, problem)

        return handler


router = APIRouter(
    prefix="/v2/ingest",
    tags=["github-actions-ingest"],
    route_class=GithubActionsIngestRoute,
)


def get_github_actions_authenticator(
    request: Request,
    session: AsyncSession = SessionDep,
) -> GithubActionsRequestAuthenticator:
    override = getattr(request.app.state, "github_actions_authenticator", None)
    if override is not None:
        return cast(GithubActionsRequestAuthenticator, override)
    from app.infrastructure.github_actions_ingest_auth import (
        SqlAlchemyGithubActionsRequestAuthenticator,
    )

    return SqlAlchemyGithubActionsRequestAuthenticator(
        session,
        request.app.state.settings,
        jwks=_JWKS,
    )


def get_github_actions_ingest_workflow(
    request: Request,
    session: AsyncSession = SessionDep,
) -> GithubActionsIngestWorkflow:
    override = getattr(request.app.state, "github_actions_ingest_workflow", None)
    if override is not None:
        return cast(GithubActionsIngestWorkflow, override)
    from app.infrastructure.github_oidc_ingest import SqlAlchemyGithubOidcIngestWorkflow

    return SqlAlchemyGithubOidcIngestWorkflow(
        session,
        github_usage_limits=request.app.state.settings.github_ingest_usage_limits,
        shared_usage_limits=request.app.state.settings.shared_ingest_usage_limits,
    )


@router.post("/github-actions")
async def upload_github_actions_result(
    request: Request,
    session: AsyncSession = SessionDep,
) -> JSONResponse:
    """Authenticate before streaming, then validate, authorize, and persist."""
    settings = request.app.state.settings
    if not getattr(settings, "github_oidc_ingest_enabled", False):
        return JSONResponse({"detail": "not found"}, status_code=404)
    if not all(
        isinstance(value, str) and value
        for value in (
            getattr(settings, "public_base_url", ""),
            getattr(settings, "github_app_id", ""),
            getattr(settings, "github_app_private_key_path", ""),
        )
    ):
        raise _problem("github_verification_failed")

    now = dt.datetime.now(dt.timezone.utc)
    authenticator = get_github_actions_authenticator(request, session)
    claims = await authenticator.authenticate(_bearer_token(request), now=now)
    expected_key = f"{claims.repository_id}:{claims.run_id}:{claims.run_attempt}"
    if request.headers.get("idempotency-key") != expected_key:
        raise _problem("artifact_mismatch")
    principal = await authenticator.authorize(claims, now=now)

    upload = await read_bounded_multipart(
        request,
        wire_bytes=ENVELOPE_LIMITS_V2.wire_bytes,
        parsed_bytes=ENVELOPE_LIMITS_V2.parsed_bytes,
        part_limits=_PART_LIMITS,
        required_parts=REQUIRED_PARTS,
        media_types=PART_MEDIA_TYPES,
    )
    envelope = build_validated_envelope_v2(
        upload.parts,
        schema_validator=CheckedInEnvelopeSchemaValidator(),
    )
    validate_github_payload_metadata(claims, envelope.metadata)
    workflow = get_github_actions_ingest_workflow(request, session)
    result = await workflow.ingest(
        GithubIngestCommand(
            project_id=principal.project_id,
            repository=claims.repository,
            github_repository_id=principal.github_repository_id,
            github_owner_id=principal.github_owner_id,
            github_run_id=principal.github_run_id,
            github_run_attempt=principal.github_run_attempt,
            accepted_bytes=upload.wire_bytes,
            envelope=envelope,
            public_base_url=settings.public_base_url,
            correlation_id=request.state.correlation_id,
        )
    )
    _log_success(
        request,
        result=result,
        wire_bytes=upload.wire_bytes,
        finding_count=len(cast(list[Any], envelope.findings["findings"])),
        scanner_count=len(cast(list[Any], envelope.findings["scanners"])),
    )
    return _success_response(result, correlation_id=request.state.correlation_id)


def _bearer_token(request: Request) -> str:
    values = request.headers.getlist("authorization")
    if len(values) != 1 or not values[0].startswith("Bearer "):
        raise _problem("invalid_credential")
    token = values[0][7:]
    if not token or len(token.encode("utf-8")) > 16 * 1024:
        raise _problem("invalid_credential")
    return token


def _success_response(result: GithubIngestResult, *, correlation_id: str) -> JSONResponse:
    status = 201
    if result.outcome is GithubIngestOutcome.REPLAYED:
        status = 200
    elif result.outcome is GithubIngestOutcome.IN_PROGRESS:
        status = 202
    headers = {}
    if result.retry_after_seconds is not None:
        headers["Retry-After"] = str(result.retry_after_seconds)
    return JSONResponse(
        {
            "run_id": result.run_id,
            "project_id": result.project_id,
            "repository": {"provider": "github", "full_name": result.repository},
            "run_url": result.run_url,
            "status": result.status,
            "replayed": result.outcome is GithubIngestOutcome.REPLAYED,
            "request_id": correlation_id,
        },
        status_code=status,
        headers=headers,
    )


def _duration_ms(request: Request) -> int:
    started = getattr(request.state, "github_ingest_started", time.monotonic())
    return max(0, round((time.monotonic() - started) * 1000))


def _log_rejection(request: Request, *, status: int, code: str) -> None:
    safe_code = code if code in _POLICIES else "internal_persistence_failed"
    _LOGGER.info(
        render_request_signal(
            IngestRequestSignal(
                origin="github",
                outcome="rejected",
                status_code=status,
                duration_ms=_duration_ms(request),
                code=safe_code,
                correlation_id=request.state.correlation_id,
            )
        )
    )


def _log_success(
    request: Request,
    *,
    result: GithubIngestResult,
    wire_bytes: int,
    finding_count: int,
    scanner_count: int,
) -> None:
    status_code = 201
    if result.outcome is GithubIngestOutcome.REPLAYED:
        status_code = 200
    elif result.outcome is GithubIngestOutcome.IN_PROGRESS:
        status_code = 202
    _LOGGER.info(
        render_request_signal(
            IngestRequestSignal(
                origin="github",
                outcome=result.outcome.value,
                status_code=status_code,
                duration_ms=_duration_ms(request),
                code=f"scan_{result.outcome.value}",
                correlation_id=request.state.correlation_id,
                wire_bytes=wire_bytes,
                finding_count=finding_count,
                scanner_count=scanner_count,
                project_id=result.project_id,
                replayed=result.outcome is GithubIngestOutcome.REPLAYED,
            )
        )
    )


def _oidc_problem(code: str) -> IngestProblem:
    safe_code = code if code in _POLICIES else "oidc_invalid"
    return _problem(safe_code)


def _problem(code: str) -> IngestProblem:
    policy = _POLICIES.get(code, _POLICIES["internal_persistence_failed"])
    headers = {"Retry-After": "30"} if policy.retry_after else {}
    if policy.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return IngestProblem(
        status=policy.status,
        code=policy.code,
        title="GitHub Actions upload rejected",
        detail="The GitHub Actions result upload could not be accepted.",
        retryable=policy.retryable,
        headers=headers,
    )


__all__ = [
    "get_github_actions_authenticator",
    "get_github_actions_ingest_workflow",
    "router",
]
