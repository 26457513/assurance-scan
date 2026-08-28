"""Strict version-one HTTP adapter for authenticated local scan uploads."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from jsonschema import Draft202012Validator
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks

from app.api.deps_scan_token import require_scan_token_principal
from app.api.deps import SessionDep
from app.config import account_identity_is_ready
from app.api.problem_details import (
    IngestProblem,
    problem_from_http_exception,
    problem_response,
)
from app.api.schemas.local_ingest import (
    LocalScanIngestCommand,
    LocalScanIngestOutcome,
    LocalScanIngestResult,
    LocalScanIngestWorkflow,
    LocalScanWorkflowError,
)
from app.modules.atomic.access.scan_token import ScanTokenPrincipal
from app.modules.atomic.ingestion.data_redactor import redact_json
from app.modules.atomic.ingestion.operational_signals import (
    LocalIngestRequestSignal,
    render_request_signal,
)
from app.modules.atomic.provenance.repository_identity import (
    InvalidRepositoryIdentityError,
    normalize_github_repository_key,
)
from app.modules.shared.contracts.local_scan import SCHEMA_VERSION, UPLOAD_LIMITS, UploadLimits


_PART_LIMITS = {
    "metadata": UPLOAD_LIMITS.metadata_bytes,
    "findings": UPLOAD_LIMITS.findings_bytes,
    "sarif": UPLOAD_LIMITS.sarif_bytes,
    "sbom": UPLOAD_LIMITS.sbom_bytes,
}
_REQUIRED_PARTS = frozenset(("metadata", "findings"))
_JSON_MEDIA_TYPES = {
    "metadata": frozenset(("application/json",)),
    "findings": frozenset(("application/json",)),
    "sarif": frozenset(("application/json", "application/sarif+json")),
    "sbom": frozenset(("application/json", "application/vnd.cyclonedx+json")),
}
_ARCHIVE_SIGNATURES = (b"PK\x03\x04", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00")
_UUID_V4_LENGTH = 36
_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "resources" / "schemas"
_LOGGER = logging.getLogger(__name__)


class IngestAPIRoute(APIRoute):
    """Ensure dependency and route failures share the problem-details shape."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            request.state.local_ingest_started = time.monotonic()
            try:
                return await original(request)
            except IngestProblem as exc:
                _log_rejection(request, status=exc.status, code=exc.code)
                return problem_response(request, exc)
            except HTTPException as exc:
                problem = problem_from_http_exception(exc)
                _log_rejection(request, status=problem.status, code=problem.code)
                return problem_response(request, problem)
            except LocalScanWorkflowError as exc:
                _log_rejection(request, status=exc.status, code=exc.code)
                headers = {}
                if exc.retry_after_seconds is not None:
                    headers["Retry-After"] = str(exc.retry_after_seconds)
                return problem_response(
                    request,
                    IngestProblem(
                        status=exc.status,
                        code=exc.code,
                        title=exc.title,
                        detail=exc.detail,
                        retryable=exc.retryable,
                        limits=exc.limits,
                        headers=headers,
                    ),
                )
            except Exception:
                _log_rejection(request, status=500, code="internal_error")
                return problem_response(
                    request,
                    IngestProblem(
                        status=500,
                        code="internal_error",
                        title="Internal server error",
                        detail="The local scan request could not be completed.",
                        retryable=True,
                    ),
                )

        return handler


router = APIRouter(
    prefix="/v1/ingest",
    tags=["local-ingest"],
    route_class=IngestAPIRoute,
)


def require_local_ingest_enabled(request: Request) -> None:
    """Fail closed until an operator explicitly enables local ingest."""
    settings = request.app.state.settings
    if not settings.local_ingest_enabled or not account_identity_is_ready(settings):
        raise IngestProblem(
            status=503,
            code="local_ingest_disabled",
            title="Local ingest is disabled",
            detail="This Assurance Scan instance does not accept local scan uploads.",
        )


def get_local_scan_ingest_workflow(
    request: Request,
    session: Any = SessionDep,
) -> LocalScanIngestWorkflow:
    """Resolve a test override or the production same-session composition."""
    workflow = getattr(request.app.state, "local_scan_ingest_workflow", None)
    if workflow is not None:
        return cast(LocalScanIngestWorkflow, workflow)
    from app.infrastructure.local_scan_ingest import SqlAlchemyLocalScanWorkflow

    return SqlAlchemyLocalScanWorkflow(
        session,
        public_base_url=request.app.state.settings.public_base_url or str(request.base_url),
        usage_limits=getattr(
            request.app.state.settings,
            "local_ingest_usage_limits",
            None,
        ),
    )


@router.get("/capabilities")
async def capabilities(
    request: Request,
    _enabled: None = Depends(require_local_ingest_enabled),
    _principal: ScanTokenPrincipal = Depends(require_scan_token_principal),
) -> dict[str, Any]:
    """Advertise the exact payload version and hard application ceilings."""
    limits = _request_upload_limits(request)
    return {
        "api_version": "v1",
        "supported_schema_versions": [SCHEMA_VERSION],
        "upload_media_type": "multipart/form-data",
        "parts": {
            "required": ["metadata", "findings"],
            "optional": ["sarif", "sbom"],
        },
        "limits": {
            "wire_bytes": limits.wire_bytes,
            "parsed_bytes": limits.parsed_bytes,
            "metadata_bytes": limits.metadata_bytes,
            "findings_bytes": limits.findings_bytes,
            "sarif_bytes": limits.sarif_bytes,
            "sbom_bytes": limits.sbom_bytes,
            "findings_count": limits.findings_count,
            "scanner_results": limits.scanner_results,
            "json_depth": limits.json_depth,
        },
    }


@router.get("/whoami")
async def whoami(
    _enabled: None = Depends(require_local_ingest_enabled),
    principal: ScanTokenPrincipal = Depends(require_scan_token_principal),
) -> dict[str, Any]:
    """Validate credentials before the CLI persists them on the host."""
    return {
        "account": principal.user_email,
        "token_label": principal.token_label,
        "scopes": [principal.scope],
        "expires_at": principal.expires_at.isoformat(),
    }


@router.post("/local-scans")
async def upload_local_scan(
    request: Request,
    _enabled: None = Depends(require_local_ingest_enabled),
    principal: ScanTokenPrincipal = Depends(require_scan_token_principal),
    workflow: LocalScanIngestWorkflow = Depends(get_local_scan_ingest_workflow),
) -> JSONResponse:
    """Validate a bounded multipart bundle before invoking durable ingestion."""
    limits = _request_upload_limits(request)
    idempotency_key = _validate_idempotency_key(request.headers.get("idempotency-key"))
    upload = await _read_multipart(request, limits)
    parts = upload.parts
    metadata = _load_json_object(parts["metadata"], part="metadata", json_depth=limits.json_depth)
    findings = _load_json_object(parts["findings"], part="findings", json_depth=limits.json_depth)
    _validate_supported_version(metadata, part="metadata")
    _validate_supported_version(findings, part="findings")
    _validate_schema(metadata, "local-scan-metadata.v1.schema.json", part="metadata")
    _validate_schema(findings, "local-scan-findings.v1.schema.json", part="findings")
    _validate_result_limits(findings, limits)
    if metadata["request_id"] != idempotency_key:
        raise IngestProblem(
            status=400,
            code="idempotency_key_mismatch",
            title="Idempotency key does not match metadata",
            detail="Idempotency-Key must equal metadata.request_id.",
        )
    _require_canary_repository(request, metadata)
    optional_documents: list[Any] = []
    for artifact in ("sarif", "sbom"):
        if artifact in parts:
            optional_documents.append(
                _load_json_value(parts[artifact], part=artifact, json_depth=limits.json_depth)
            )

    payload_hash = _payload_hash(metadata, parts)
    result = await workflow.ingest_local_scan(
        LocalScanIngestCommand(
            principal=principal,
            idempotency_key=idempotency_key,
            metadata=metadata,
            findings=findings,
            accepted_bytes=upload.wire_bytes,
            findings_bytes=parts["findings"],
            sarif_bytes=parts.get("sarif"),
            sbom_bytes=parts.get("sbom"),
            payload_hash=payload_hash,
        )
    )
    redaction_count = redact_json(findings).replacements
    redaction_count += sum(
        redact_json(document).replacements for document in optional_documents
    )
    _log_success(
        request,
        result=result,
        wire_bytes=upload.wire_bytes,
        finding_count=len(cast(list[Any], findings["findings"])),
        scanner_count=len(cast(list[Any], findings["scanners"])),
        redaction_count=redaction_count,
    )
    return _success_response(result)


@router.get("/local-scans/requests/{request_id}")
async def local_scan_request_status(
    request: Request,
    request_id: str,
    _enabled: None = Depends(require_local_ingest_enabled),
    principal: ScanTokenPrincipal = Depends(require_scan_token_principal),
    session: Any = SessionDep,
) -> JSONResponse:
    """Return only the authenticated user's durable request state."""
    canonical_request_id = _validate_idempotency_key(request_id)
    from app.infrastructure.local_scan_ingest import get_local_request_status

    status = await get_local_request_status(
        session,
        user_id=principal.user_id,
        request_id=canonical_request_id,
    )
    if status is None:
        raise IngestProblem(
            status=404,
            code="scan_request_not_found",
            title="Scan request not found",
            detail="The scan request is not available.",
        )
    if status.state == "tombstoned":
        raise IngestProblem(
            status=410,
            code="idempotency_tombstoned",
            title="Scan request is no longer available",
            detail="This request belongs to a deleted scan and cannot yet be reused.",
        )
    retry_after = None
    if status.state == "processing":
        retry_after = _retry_after_seconds(status.lease_expires_at)
    body = {
        "request_id": canonical_request_id,
        "status": status.state,
        "run_id": status.run_id,
        "project_id": status.project_id,
        "repository": {"provider": "github", "full_name": status.repository},
        "run_url": (
            None
            if status.run_id is None
            else f"{request.app.state.settings.public_base_url.rstrip('/')}/scans/{status.run_id}"
        ),
    }
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    return JSONResponse(body, headers=headers)


def _validate_idempotency_key(raw: str | None) -> str:
    if raw is None or len(raw) != _UUID_V4_LENGTH or raw != raw.lower():
        raise _invalid_idempotency_key()
    try:
        parsed = uuid.UUID(raw)
    except ValueError as exc:
        raise _invalid_idempotency_key() from exc
    if parsed.version != 4 or str(parsed) != raw:
        raise _invalid_idempotency_key()
    return raw


def _invalid_idempotency_key() -> IngestProblem:
    return IngestProblem(
        status=400,
        code="invalid_idempotency_key",
        title="Invalid idempotency key",
        detail="Idempotency-Key must be a canonical lowercase UUIDv4.",
    )


@dataclass(frozen=True)
class _MultipartUpload:
    parts: dict[str, bytes]
    wire_bytes: int


async def _read_multipart(request: Request, limits: UploadLimits) -> _MultipartUpload:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise IngestProblem(
                status=400,
                code="invalid_content_length",
                title="Invalid Content-Length",
                detail="Content-Length must be a non-negative integer.",
            ) from exc
        if declared_length < 0:
            raise IngestProblem(
                status=400,
                code="invalid_content_length",
                title="Invalid Content-Length",
                detail="Content-Length must be a non-negative integer.",
            )
        if declared_length > limits.wire_bytes:
            raise _size_problem("wire_bytes", limits.wire_bytes)

    media_type, parameters = parse_options_header(request.headers.get("content-type", ""))
    if media_type != b"multipart/form-data" or not parameters.get(b"boundary"):
        raise IngestProblem(
            status=415,
            code="unsupported_media_type",
            title="Unsupported media type",
            detail="Content-Type must be multipart/form-data with a boundary.",
        )
    part_limits = (
        _PART_LIMITS
        if limits is UPLOAD_LIMITS
        else {
            "metadata": limits.metadata_bytes,
            "findings": limits.findings_bytes,
            "sarif": limits.sarif_bytes,
            "sbom": limits.sbom_bytes,
        }
    )
    collector = _MultipartCollector(part_limits, parsed_bytes=limits.parsed_bytes)
    parser = MultipartParser(
        parameters[b"boundary"],
        collector.callbacks,
        max_size=limits.wire_bytes,
    )
    wire_bytes = 0
    try:
        async for chunk in request.stream():
            wire_bytes += len(chunk)
            if wire_bytes > limits.wire_bytes:
                raise _size_problem("wire_bytes", limits.wire_bytes)
            parser.write(chunk)
        parser.finalize()
    except IngestProblem:
        raise
    except Exception as exc:
        raise IngestProblem(
            status=400,
            code="malformed_multipart",
            title="Malformed multipart request",
            detail="The multipart request could not be parsed.",
        ) from exc
    return _MultipartUpload(parts=collector.finish(), wire_bytes=wire_bytes)


class _MultipartCollector:
    """Incrementally collect only the four bounded protocol parts."""

    def __init__(self, part_limits: Mapping[str, int], *, parsed_bytes: int) -> None:
        self.part_limits = part_limits
        self.parsed_bytes = parsed_bytes
        self.parts: dict[str, bytes] = {}
        self.header_field = bytearray()
        self.header_value = bytearray()
        self.headers: dict[bytes, bytes] = {}
        self.name: str | None = None
        self.data = bytearray()
        self.ended = False
        self.callbacks: MultipartCallbacks = {
            "on_part_begin": self.on_part_begin,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
            "on_end": self.on_end,
        }

    def on_part_begin(self) -> None:
        self.headers = {}
        self.name = None
        self.data = bytearray()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self.header_field.extend(data[start:end])

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self.header_value.extend(data[start:end])

    def on_header_end(self) -> None:
        key = bytes(self.header_field).strip().lower()
        if not key or key in self.headers:
            raise _multipart_shape_problem()
        self.headers[key] = bytes(self.header_value).strip()
        self.header_field.clear()
        self.header_value.clear()

    def on_headers_finished(self) -> None:
        disposition, options = parse_options_header(self.headers.get(b"content-disposition", b""))
        raw_name = options.get(b"name", b"")
        try:
            name = raw_name.decode("ascii")
        except UnicodeDecodeError as exc:
            raise _multipart_shape_problem() from exc
        if disposition != b"form-data" or name not in self.part_limits or name in self.parts:
            raise _multipart_shape_problem()
        content_type, _ = parse_options_header(self.headers.get(b"content-type", b""))
        accepted_types = _JSON_MEDIA_TYPES[name]
        if content_type.decode("ascii", errors="ignore").lower() not in accepted_types:
            raise IngestProblem(
                status=415,
                code="unsupported_part_media_type",
                title="Unsupported part media type",
                detail=f"Part '{name}' must declare a supported JSON media type.",
            )
        self.name = name

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self.name is None:
            raise _multipart_shape_problem()
        chunk = data[start:end]
        if len(self.data) + len(chunk) > self.part_limits[self.name]:
            raise _size_problem(f"{self.name}_bytes", self.part_limits[self.name])
        self.data.extend(chunk)

    def on_part_end(self) -> None:
        if self.name is None:
            raise _multipart_shape_problem()
        value = bytes(self.data)
        if value.startswith(_ARCHIVE_SIGNATURES):
            raise IngestProblem(
                status=415,
                code="archive_not_supported",
                title="Archives are not supported",
                detail="Upload JSON artifacts directly; archive payloads are rejected.",
            )
        self.parts[self.name] = value

    def on_end(self) -> None:
        self.ended = True

    def finish(self) -> dict[str, bytes]:
        if not self.ended or not _REQUIRED_PARTS.issubset(self.parts):
            raise _multipart_shape_problem()
        parsed_size = sum(len(value) for value in self.parts.values())
        if parsed_size > self.parsed_bytes:
            raise _size_problem("parsed_bytes", self.parsed_bytes)
        return self.parts


def _multipart_shape_problem() -> IngestProblem:
    return IngestProblem(
        status=400,
        code="invalid_multipart_parts",
        title="Invalid multipart parts",
        detail="Provide metadata and findings exactly once, with optional sarif and sbom exactly once.",
    )


def _size_problem(limit_name: str, maximum: int) -> IngestProblem:
    return IngestProblem(
        status=413,
        code="payload_too_large",
        title="Payload is too large",
        detail="The upload exceeds an application size limit.",
        limits={limit_name: maximum},
    )


def _load_json_object(payload: bytes, *, part: str, json_depth: int) -> dict[str, Any]:
    value = _load_json_value(payload, part=part, json_depth=json_depth)
    if not isinstance(value, dict):
        raise _schema_problem(part)
    return cast(dict[str, Any], value)


def _load_json_value(payload: bytes, *, part: str, json_depth: int) -> Any:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise IngestProblem(
                    status=400,
                    code="duplicate_json_key",
                    title="Duplicate JSON key",
                    detail=f"Part '{part}' contains a duplicate object key.",
                )
            result[key] = value
        return result

    def reject_non_finite(_value: str) -> None:
        raise ValueError("non-finite JSON number")

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_non_finite,
        )
    except IngestProblem:
        raise
    except RecursionError as exc:
        raise _json_depth_problem(part, json_depth) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestProblem(
            status=400,
            code="malformed_json",
            title="Malformed JSON",
            detail=f"Part '{part}' must contain valid UTF-8 JSON.",
        ) from exc
    except ValueError as exc:
        raise IngestProblem(
            status=400,
            code="malformed_json",
            title="Malformed JSON",
            detail=f"Part '{part}' must contain valid UTF-8 JSON.",
        ) from exc
    if _json_depth_exceeded(value, json_depth):
        raise _json_depth_problem(part, json_depth)
    return value


def _json_depth_exceeded(value: Any, maximum: int) -> bool:
    stack = [(value, 0)]
    while stack:
        item, parent_depth = stack.pop()
        if isinstance(item, dict):
            depth = parent_depth + 1
            if depth > maximum:
                return True
            stack.extend((child, depth) for child in item.values())
        elif isinstance(item, list):
            depth = parent_depth + 1
            if depth > maximum:
                return True
            stack.extend((child, depth) for child in item)
    return False


def _json_depth_problem(part: str, maximum: int) -> IngestProblem:
    return IngestProblem(
        status=422,
        code="json_depth_exceeded",
        title="JSON nesting limit exceeded",
        detail=f"Part '{part}' exceeds the maximum JSON nesting depth.",
        limits={"json_depth": maximum},
    )


def _validate_supported_version(document: Mapping[str, Any], *, part: str) -> None:
    if document.get("schema_version") != SCHEMA_VERSION:
        raise IngestProblem(
            status=422,
            code="unsupported_schema_version",
            title="Unsupported schema version",
            detail=f"Part '{part}' uses an unsupported schema version.",
            extensions={"supported_schema_versions": [SCHEMA_VERSION]},
        )


def _validate_schema(document: Mapping[str, Any], filename: str, *, part: str) -> None:
    schema = json.loads((_SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise _schema_problem(part)


def _validate_result_limits(document: Mapping[str, Any], limits: UploadLimits) -> None:
    scanners = document.get("scanners")
    findings = document.get("findings")
    if not isinstance(scanners, list) or len(scanners) > limits.scanner_results:
        raise _schema_problem("findings")
    if not isinstance(findings, list) or len(findings) > limits.findings_count:
        raise _schema_problem("findings")
    for finding in findings:
        if not isinstance(finding, dict):
            raise _schema_problem("findings")
        path = finding.get("file_path")
        message = finding.get("message")
        if isinstance(path, str) and len(path) > limits.path_chars:
            raise _schema_problem("findings")
        if not isinstance(message, str) or len(message) > limits.message_chars:
            raise _schema_problem("findings")


def _schema_problem(part: str) -> IngestProblem:
    return IngestProblem(
        status=422,
        code="schema_validation_failed",
        title="Schema validation failed",
        detail=f"Part '{part}' does not satisfy the version-one schema.",
    )


def _payload_hash(metadata: Mapping[str, Any], parts: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    for name in ("findings", "sarif", "sbom"):
        value = parts.get(name)
        if value is None:
            continue
        artifact_hash = hashlib.sha256(value).hexdigest()
        digest.update(f"\n{name}\0{len(value)}\0{artifact_hash}".encode())
    return digest.hexdigest()


def _success_response(result: LocalScanIngestResult) -> JSONResponse:
    status_code = 201
    if result.outcome is LocalScanIngestOutcome.REPLAYED:
        status_code = 200
    elif result.outcome is LocalScanIngestOutcome.IN_PROGRESS:
        status_code = 202
    body: dict[str, Any] = {
        "run_id": result.run_id,
        "project_id": result.project_id,
        "repository": {"provider": "github", "full_name": result.repository},
        "run_url": result.run_url,
        "status": result.status,
        "replayed": result.outcome is LocalScanIngestOutcome.REPLAYED,
    }
    if result.status_url is not None:
        body["status_url"] = result.status_url
    headers = {}
    if result.retry_after_seconds is not None:
        headers["Retry-After"] = str(result.retry_after_seconds)
    return JSONResponse(body, status_code=status_code, headers=headers)


def _retry_after_seconds(lease_expires_at: Any) -> int:
    from datetime import datetime, timezone

    if lease_expires_at is None:
        return 30
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
    return max(1, min(300, round((lease_expires_at - datetime.now(timezone.utc)).total_seconds())))


def _duration_ms(request: Request) -> int:
    started = getattr(request.state, "local_ingest_started", time.monotonic())
    return max(0, round((time.monotonic() - started) * 1000))


def _log_rejection(request: Request, *, status: int, code: str) -> None:
    _LOGGER.info(
        render_request_signal(
            LocalIngestRequestSignal(
                outcome="rejected",
                status_code=status,
                duration_ms=_duration_ms(request),
                code=code,
            )
        )
    )


def _log_success(
    request: Request,
    *,
    result: LocalScanIngestResult,
    wire_bytes: int,
    finding_count: int,
    scanner_count: int,
    redaction_count: int,
) -> None:
    status_code = 201
    if result.outcome is LocalScanIngestOutcome.REPLAYED:
        status_code = 200
    elif result.outcome is LocalScanIngestOutcome.IN_PROGRESS:
        status_code = 202
    _LOGGER.info(
        render_request_signal(
            LocalIngestRequestSignal(
                outcome=result.outcome.value,
                status_code=status_code,
                duration_ms=_duration_ms(request),
                code=f"scan_{result.outcome.value}",
                wire_bytes=wire_bytes,
                finding_count=finding_count,
                scanner_count=scanner_count,
                redaction_count=redaction_count,
                project_id=result.project_id,
                replayed=result.outcome is LocalScanIngestOutcome.REPLAYED,
            )
        )
    )


def _request_upload_limits(request: Request) -> UploadLimits:
    return getattr(request.app.state.settings, "local_ingest_upload_limits", UPLOAD_LIMITS)


def _require_canary_repository(request: Request, metadata: Mapping[str, Any]) -> None:
    allowlist: frozenset[str] = getattr(
        request.app.state.settings,
        "local_ingest_repository_allowlist",
        frozenset(),
    )
    if not allowlist:
        return
    target = metadata.get("project_override") or metadata.get("repository")
    try:
        key = normalize_github_repository_key(str(target))
    except InvalidRepositoryIdentityError as exc:
        raise _schema_problem("metadata") from exc
    if key not in allowlist:
        raise IngestProblem(
            status=403,
            code="repository_not_enabled",
            title="Repository is not enabled for local ingest",
            detail="This repository is outside the current local-ingest rollout.",
        )


__all__ = [
    "get_local_scan_ingest_workflow",
    "require_local_ingest_enabled",
    "router",
]
