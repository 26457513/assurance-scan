"""Stdlib HTTPS and clock adapters for streaming multipart uploads."""
from __future__ import annotations

import http.client
import secrets
import ssl
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .models import (
    HttpResponse,
    UploadBundle,
    UploadClientConfig,
    UploadClientError,
    UploadNetworkError,
    UploadResult,
)
from .service import upload_bundle


_MAX_RESPONSE_BYTES = 1024 * 1024
_CHUNK_BYTES = 64 * 1024


class SystemRetryClock:
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class StdlibUploadTransport:
    """Stream fixed protocol parts without loading outbox artifacts into memory."""

    def post_multipart(
        self,
        url: str,
        config: UploadClientConfig,
        bundle: UploadBundle,
    ) -> HttpResponse:
        boundary = f"assurance-scan-{secrets.token_hex(16)}"
        parts = _parts(bundle)
        headers_and_sizes = [
            (_part_header(boundary, name, media_type), _regular_file_size(path), path)
            for name, media_type, path in parts
        ]
        closing = f"--{boundary}--\r\n".encode()
        content_length = sum(len(header) + size + 2 for header, size, _ in headers_and_sizes)
        content_length += len(closing)
        connection, target = _connection(url, config)
        try:
            connection.putrequest("POST", target)
            connection.putheader("Authorization", f"Bearer {config.token}")
            connection.putheader("Idempotency-Key", bundle.request_id)
            connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            connection.putheader("Content-Length", str(content_length))
            connection.putheader("Accept", "application/json, application/problem+json")
            connection.endheaders()
            for header, _, path in headers_and_sizes:
                connection.send(header)
                with path.open("rb") as handle:
                    while chunk := handle.read(_CHUNK_BYTES):
                        connection.send(chunk)
                connection.send(b"\r\n")
            connection.send(closing)
            return _response(connection, config)
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise UploadNetworkError("network_error", "upload network request failed") from exc
        finally:
            connection.close()

    def get_status(self, url: str, config: UploadClientConfig) -> HttpResponse:
        connection, target = _connection(url, config)
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Authorization": f"Bearer {config.token}",
                    "Accept": "application/json, application/problem+json",
                },
            )
            return _response(connection, config)
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise UploadNetworkError("network_error", "status recovery request failed") from exc
        finally:
            connection.close()


class StdlibUploadClient:
    def __init__(self) -> None:
        self._transport = StdlibUploadTransport()
        self._clock = SystemRetryClock()

    def upload(self, bundle: UploadBundle, config: UploadClientConfig) -> UploadResult:
        return upload_bundle(bundle, config, transport=self._transport, clock=self._clock)


def _parts(bundle: UploadBundle) -> tuple[tuple[str, str, Path], ...]:
    parts = [
        ("metadata", "application/json", bundle.metadata_path),
        ("findings", "application/json", bundle.findings_path),
    ]
    if bundle.sarif_path is not None:
        parts.append(("sarif", "application/sarif+json", bundle.sarif_path))
    if bundle.sbom_path is not None:
        parts.append(("sbom", "application/vnd.cyclonedx+json", bundle.sbom_path))
    return tuple(parts)


def _part_header(boundary: str, name: str, media_type: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n'
        f"Content-Type: {media_type}\r\n\r\n"
    ).encode()


def _regular_file_size(path: Path) -> int:
    try:
        info = path.lstat()
    except OSError as exc:
        raise UploadClientError("outbox_unavailable", "an outbox artifact is unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise UploadClientError("invalid_outbox_file", "an outbox artifact is not a regular file")
    return info.st_size


def _connection(
    url: str,
    config: UploadClientConfig,
) -> tuple[http.client.HTTPConnection, str]:
    parsed = urlsplit(url)
    if parsed.hostname is None:
        raise UploadClientError("invalid_server_url", "server URL is invalid")
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    if parsed.scheme == "https":
        try:
            context = ssl.create_default_context(
                cafile=None if config.custom_ca_file is None else str(config.custom_ca_file)
            )
        except (OSError, ssl.SSLError) as exc:
            raise UploadClientError("invalid_custom_ca", "custom CA could not be loaded") from exc
        return (
            http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
                parsed.hostname,
                parsed.port,
                timeout=config.connect_timeout_seconds,
                context=context,
            ),
            target,
        )
    return (
        http.client.HTTPConnection(
            parsed.hostname,
            parsed.port,
            timeout=config.connect_timeout_seconds,
        ),
        target,
    )


def _response(
    connection: http.client.HTTPConnection,
    config: UploadClientConfig,
) -> HttpResponse:
    response = connection.getresponse()
    if connection.sock is not None:
        connection.sock.settimeout(config.response_timeout_seconds)
    body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise UploadClientError("response_too_large", "server response exceeded the client limit")
    return HttpResponse(
        response.status,
        {name.casefold(): value for name, value in response.getheaders()},
        body,
    )


__all__ = ["StdlibUploadClient", "StdlibUploadTransport", "SystemRetryClock"]
