"""RFC 9457 problem details used by the versioned ingest boundary."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class IngestProblem(Exception):
    """A safe, stable local-ingest failure suitable for an API response."""

    def __init__(
        self,
        *,
        status: int,
        code: str,
        title: str,
        detail: str,
        retryable: bool = False,
        limits: Mapping[str, int] | None = None,
        headers: Mapping[str, str] | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.retryable = retryable
        self.limits = dict(limits or {})
        self.headers = dict(headers or {})
        self.extensions = dict(extensions or {})


def problem_response(request: Request, problem: IngestProblem) -> JSONResponse:
    """Render a problem without reflecting credentials or payload content."""
    request_id = str(uuid.uuid4())
    body: dict[str, Any] = {
        "type": f"https://assurance-scan.dev/problems/{problem.code.replace('_', '-')}",
        "title": problem.title,
        "status": problem.status,
        "detail": problem.detail,
        "instance": request.url.path,
        "code": problem.code,
        "retryable": problem.retryable,
        "request_id": request_id,
        "limits": problem.limits,
    }
    body.update(problem.extensions)
    return JSONResponse(
        body,
        status_code=problem.status,
        media_type="application/problem+json",
        headers=problem.headers,
    )


def problem_from_http_exception(exc: HTTPException) -> IngestProblem:
    """Normalize authentication dependency failures without leaking decisions."""
    if exc.status_code == 401:
        return IngestProblem(
            status=401,
            code="invalid_credential",
            title="Invalid bearer credential",
            detail="A valid scan-upload bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if exc.status_code == 403:
        return IngestProblem(
            status=403,
            code="insufficient_scope",
            title="Insufficient token scope",
            detail="The bearer token is not permitted to upload scans.",
        )
    if exc.status_code == 429:
        return IngestProblem(
            status=429,
            code="authentication_rate_limited",
            title="Authentication rate limited",
            detail="Too many invalid authentication attempts were received.",
            retryable=True,
            headers={"Retry-After": exc.headers.get("Retry-After", "600") if exc.headers else "600"},
        )
    return IngestProblem(
        status=exc.status_code,
        code="request_rejected",
        title="Request rejected",
        detail="The request could not be accepted.",
    )


__all__ = [
    "IngestProblem",
    "problem_from_http_exception",
    "problem_response",
]
