"""Bounded retry and response-loss recovery for immutable outbox bundles."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from .models import (
    HttpResponse,
    UploadBundle,
    UploadClientConfig,
    UploadClientError,
    UploadDisposition,
    UploadNetworkError,
    UploadRejectedError,
    UploadResult,
)
from .ports import RetryClockPort, UploadTransportPort


_RETRYABLE_STATUSES = frozenset((408, 429, 500, 502, 503, 504))
_REDIRECT_STATUSES = frozenset((301, 302, 303, 307, 308))
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def upload_bundle(
    bundle: UploadBundle,
    config: UploadClientConfig,
    *,
    transport: UploadTransportPort,
    clock: RetryClockPort,
) -> UploadResult:
    """Upload the same outbox bundle with bounded, protocol-safe retries."""

    endpoint = _endpoint(config.base_url, config.allow_loopback_http)
    status_url = f"{endpoint}/requests/{bundle.request_id}"
    if config.max_attempts < 1 or config.max_attempts > 10:
        raise UploadClientError("invalid_retry_policy", "upload retry policy is invalid")

    delay = 1
    for attempt in range(1, config.max_attempts + 1):
        try:
            response = _post_without_cross_origin_redirects(
                endpoint,
                config,
                bundle,
                transport,
            )
        except UploadNetworkError:
            recovered = _recover_status(status_url, config, transport)
            if recovered is not None:
                return recovered
            if attempt == config.max_attempts:
                raise UploadNetworkError(
                    "network_retry_exhausted",
                    "upload could not be confirmed after bounded retries",
                ) from None
            clock.sleep(delay)
            delay = min(delay * 2, config.max_retry_delay_seconds)
            continue

        result = _successful_result(response)
        if result is not None:
            return result
        if response.status not in _RETRYABLE_STATUSES:
            raise UploadRejectedError(_problem_code(response), status=response.status)
        if attempt == config.max_attempts:
            raise UploadNetworkError(
                "server_retry_exhausted",
                "server did not accept the upload after bounded retries",
            )
        retry_after = _retry_after(response, config.max_retry_delay_seconds)
        clock.sleep(retry_after if retry_after is not None else delay)
        delay = min(delay * 2, config.max_retry_delay_seconds)
    raise AssertionError("bounded upload loop terminated unexpectedly")


def _post_without_cross_origin_redirects(
    endpoint: str,
    config: UploadClientConfig,
    bundle: UploadBundle,
    transport: UploadTransportPort,
) -> HttpResponse:
    response = transport.post_multipart(endpoint, config, bundle)
    for _ in range(2):
        if response.status not in _REDIRECT_STATUSES:
            return response
        location = response.headers.get("location")
        if not location:
            raise UploadClientError("invalid_redirect", "server returned an invalid redirect")
        redirected = urljoin(endpoint, location)
        if _origin(redirected) != _origin(endpoint):
            raise UploadClientError(
                "cross_origin_redirect_blocked",
                "upload redirect changed origin and was blocked",
            )
        response = transport.post_multipart(redirected, config, bundle)
    if response.status in _REDIRECT_STATUSES:
        raise UploadClientError("redirect_limit", "upload redirect limit exceeded")
    return response


def _recover_status(
    status_url: str,
    config: UploadClientConfig,
    transport: UploadTransportPort,
) -> UploadResult | None:
    try:
        response = transport.get_status(status_url, config)
    except UploadNetworkError:
        return None
    if response.status != 200:
        return None
    document = _json_object(response)
    state = document.get("status")
    if state == "completed" and isinstance(document.get("run_id"), str):
        return _result(document, UploadDisposition.REPLAYED, response.status)
    if state == "processing":
        return _result(
            document,
            UploadDisposition.IN_PROGRESS,
            response.status,
            retry_after=_retry_after(response, config.max_retry_delay_seconds),
        )
    return None


def _successful_result(response: HttpResponse) -> UploadResult | None:
    if response.status not in {200, 201, 202}:
        return None
    document = _json_object(response)
    if response.status == 202 or document.get("status") == "processing":
        return _result(
            document,
            UploadDisposition.IN_PROGRESS,
            response.status,
            retry_after=_retry_after(response, 300),
        )
    disposition = UploadDisposition.REPLAYED if response.status == 200 else UploadDisposition.UPLOADED
    return _result(document, disposition, response.status)


def _result(
    document: dict[str, Any],
    disposition: UploadDisposition,
    status: int,
    *,
    retry_after: int | None = None,
) -> UploadResult:
    return UploadResult(
        disposition=disposition,
        status=status,
        run_id=document.get("run_id") if isinstance(document.get("run_id"), str) else None,
        project_id=(
            document.get("project_id") if isinstance(document.get("project_id"), int) else None
        ),
        run_url=document.get("run_url") if isinstance(document.get("run_url"), str) else None,
        retry_after_seconds=retry_after,
    )


def _json_object(response: HttpResponse) -> dict[str, Any]:
    try:
        document = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UploadClientError("invalid_server_response", "server response was not valid JSON") from exc
    if not isinstance(document, dict):
        raise UploadClientError("invalid_server_response", "server response was not a JSON object")
    return document


def _problem_code(response: HttpResponse) -> str:
    try:
        code = _json_object(response).get("code")
    except UploadClientError:
        code = None
    if isinstance(code, str) and _SAFE_CODE.fullmatch(code):
        return code
    return f"http_{response.status}"


def _retry_after(response: HttpResponse, maximum: int) -> int | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0, min(maximum, int(raw)))
    except ValueError:
        try:
            target = parsedate_to_datetime(raw)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            seconds = round((target - datetime.now(timezone.utc)).total_seconds())
            return max(0, min(maximum, seconds))
        except (TypeError, ValueError, OverflowError):
            return None


def _endpoint(base_url: str, allow_loopback_http: bool) -> str:
    parsed = urlsplit(base_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise UploadClientError("invalid_server_url", "server URL is invalid")
    if parsed.scheme == "https" and parsed.hostname:
        pass
    elif parsed.scheme == "http" and allow_loopback_http and _is_loopback(parsed.hostname):
        pass
    else:
        raise UploadClientError("https_required", "HTTPS is required for scan uploads")
    return f"{parsed.scheme}://{parsed.netloc}/api/v1/ingest/local-scans"


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname or "", parsed.port


def _is_loopback(hostname: str | None) -> bool:
    if hostname == "localhost":
        return True
    if hostname is None:
        return False
    try:
        import ipaddress

        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


__all__ = ["upload_bundle"]
