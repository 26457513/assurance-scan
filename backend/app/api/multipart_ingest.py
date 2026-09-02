"""Reusable bounded multipart reader for versioned ingest adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header
from starlette.requests import ClientDisconnect

from app.api.problem_details import IngestProblem

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks


_ARCHIVE_SIGNATURES = (b"PK\x03\x04", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00")


@dataclass(frozen=True)
class MultipartUpload:
    parts: dict[str, bytes]
    wire_bytes: int


async def read_bounded_multipart(
    request: Request,
    *,
    wire_bytes: int,
    parsed_bytes: int,
    part_limits: Mapping[str, int],
    required_parts: frozenset[str],
    media_types: Mapping[str, tuple[str, ...]],
) -> MultipartUpload:
    """Stream exactly one bounded copy of each allowlisted protocol part."""
    _reject_content_encoding(request)
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError as exc:
            raise _problem(400, "malformed_multipart", "Content-Length is invalid.") from exc
        if declared_bytes < 0:
            raise _problem(400, "malformed_multipart", "Content-Length is invalid.")
        if declared_bytes > wire_bytes:
            raise _size_problem("wire_bytes", wire_bytes)

    outer_type, parameters = parse_options_header(request.headers.get("content-type", ""))
    if outer_type != b"multipart/form-data" or not parameters.get(b"boundary"):
        raise _problem(415, "invalid_content_type", "Content-Type must be multipart/form-data.")
    collector = _MultipartCollector(
        part_limits,
        required_parts=required_parts,
        media_types=media_types,
        parsed_bytes=parsed_bytes,
    )
    parser = MultipartParser(parameters[b"boundary"], collector.callbacks, max_size=wire_bytes)
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > wire_bytes:
                raise _size_problem("wire_bytes", wire_bytes)
            parser.write(chunk)
        parser.finalize()
    except IngestProblem:
        raise
    except ClientDisconnect as exc:
        raise _problem(400, "malformed_multipart", "The multipart request is incomplete.") from exc
    except Exception as exc:
        raise _problem(400, "malformed_multipart", "The multipart request is invalid.") from exc
    return MultipartUpload(collector.finish(), received)


class _MultipartCollector:
    def __init__(
        self,
        part_limits: Mapping[str, int],
        *,
        required_parts: frozenset[str],
        media_types: Mapping[str, tuple[str, ...]],
        parsed_bytes: int,
    ) -> None:
        self._part_limits = part_limits
        self._required_parts = required_parts
        self._media_types = media_types
        self._parsed_bytes = parsed_bytes
        self.parts: dict[str, bytes] = {}
        self._headers: dict[bytes, bytes] = {}
        self._header_field = bytearray()
        self._header_value = bytearray()
        self._name: str | None = None
        self._data = bytearray()
        self._ended = False
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
        self._headers = {}
        self._name = None
        self._data = bytearray()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_field.extend(data[start:end])

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value.extend(data[start:end])

    def on_header_end(self) -> None:
        key = bytes(self._header_field).strip().lower()
        if not key or key in self._headers:
            raise _shape_problem("duplicate_part")
        self._headers[key] = bytes(self._header_value).strip()
        self._header_field.clear()
        self._header_value.clear()

    def on_headers_finished(self) -> None:
        if b"content-encoding" in self._headers or b"content-transfer-encoding" in self._headers:
            raise _problem(
                415,
                "unsupported_content_encoding",
                "Encoded multipart parts are not supported.",
            )
        disposition, options = parse_options_header(self._headers.get(b"content-disposition", b""))
        try:
            name = options.get(b"name", b"").decode("ascii")
        except UnicodeDecodeError as exc:
            raise _shape_problem("unexpected_part") from exc
        if disposition != b"form-data" or name not in self._part_limits:
            raise _shape_problem("unexpected_part")
        if name in self.parts:
            raise _shape_problem("duplicate_part")
        if not _media_type_allowed(self._headers.get(b"content-type", b""), self._media_types[name]):
            raise _problem(
                415,
                "invalid_part_media_type",
                "A multipart part has an unsupported media type.",
            )
        self._name = name

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._name is None:
            raise _shape_problem("unexpected_part")
        chunk = data[start:end]
        maximum = self._part_limits[self._name]
        if len(self._data) + len(chunk) > maximum:
            raise _size_problem(f"{self._name}_bytes", maximum)
        self._data.extend(chunk)

    def on_part_end(self) -> None:
        if self._name is None:
            raise _shape_problem("unexpected_part")
        value = bytes(self._data)
        if value.startswith(_ARCHIVE_SIGNATURES):
            raise _problem(415, "unsupported_content_encoding", "Archive parts are not supported.")
        self.parts[self._name] = value

    def on_end(self) -> None:
        self._ended = True

    def finish(self) -> dict[str, bytes]:
        if not self._ended or not self._required_parts.issubset(self.parts):
            raise _shape_problem("unexpected_part")
        if sum(map(len, self.parts.values())) > self._parsed_bytes:
            raise _size_problem("parsed_bytes", self._parsed_bytes)
        return self.parts


def _media_type_allowed(raw: bytes, allowed: tuple[str, ...]) -> bool:
    media_type, parameters = parse_options_header(raw)
    normalized_type = media_type.decode("ascii", errors="ignore").casefold()
    charset = parameters.get(b"charset")
    normalized_charset = None if charset is None else charset.decode("ascii", errors="ignore").casefold()
    if set(parameters) - {b"charset"}:
        return False
    for candidate in allowed:
        expected_type, separator, expected_charset = candidate.partition("; charset=")
        if normalized_type == expected_type and (
            (not separator and normalized_charset is None)
            or (separator and normalized_charset == expected_charset)
        ):
            return True
    return False


def _reject_content_encoding(request: Request) -> None:
    if request.headers.get("content-encoding") or request.headers.get("transfer-encoding"):
        raise _problem(
            415,
            "unsupported_content_encoding",
            "Encoded request bodies are not supported.",
        )


def _shape_problem(code: str) -> IngestProblem:
    return _problem(400, code, "The multipart part set is invalid.")


def _size_problem(name: str, maximum: int) -> IngestProblem:
    return IngestProblem(
        status=413,
        code="wire_limit_exceeded",
        title="Upload limit exceeded",
        detail="The request exceeds an application size limit.",
        limits={name: maximum},
    )


def _problem(status: int, code: str, detail: str) -> IngestProblem:
    return IngestProblem(status=status, code=code, title="GitHub upload rejected", detail=detail)


__all__ = ["MultipartUpload", "read_bounded_multipart"]
