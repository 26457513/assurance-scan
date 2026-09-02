"""Streaming stdlib transport for the socket-free GitHub OIDC uploader."""
from __future__ import annotations

import http.client
import secrets
import ssl
from urllib.parse import urlsplit, urlunsplit

from app.modules.atomic.ingestion.github_oidc_upload_client import (
    GithubUploadBundle,
    GithubUploadConfig,
    GithubUploadError,
    GithubUploadNetworkError,
    GithubUploadResponse,
)


_CHUNK_BYTES = 64 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024
_MEDIA_TYPES = {
    "metadata": "application/json; charset=utf-8",
    "findings": "application/json; charset=utf-8",
    "source_contexts": "application/json; charset=utf-8",
    "sarif": "application/sarif+json",
    "sbom": "application/vnd.cyclonedx+json",
}


class StdlibGithubOidcUploadTransport:
    """Stream allowlisted result files with Content-Length and no redirects."""

    def post(
        self,
        endpoint: str,
        bundle: GithubUploadBundle,
        config: GithubUploadConfig,
    ) -> GithubUploadResponse:
        boundary = f"assurance-scan-{secrets.token_hex(16)}"
        parts = tuple(
            (name, _header(boundary, name), path.stat().st_size, path)
            for name, path in bundle.parts.items()
        )
        closing = f"--{boundary}--\r\n".encode("ascii")
        length = sum(len(header) + size + 2 for _, header, size, _ in parts) + len(closing)
        connection, target = _connection(endpoint, config)
        try:
            connection.putrequest("POST", target, skip_accept_encoding=True)
            connection.putheader("Authorization", f"Bearer {config.oidc_jwt}")
            connection.putheader("Idempotency-Key", bundle.idempotency_key)
            connection.putheader("X-Assurance-Payload-SHA256", bundle.payload_hash)
            connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            connection.putheader("Content-Length", str(length))
            connection.putheader("Accept", "application/json, application/problem+json")
            connection.endheaders()
            for _, header, _, path in parts:
                connection.send(header)
                with path.open("rb") as handle:
                    while chunk := handle.read(_CHUNK_BYTES):
                        connection.send(chunk)
                connection.send(b"\r\n")
            connection.send(closing)
            return _response(connection, config)
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise GithubUploadNetworkError from exc
        finally:
            connection.close()


def _header(boundary: str, name: str) -> bytes:
    if name not in _MEDIA_TYPES:
        raise GithubUploadError("invalid_bundle")
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n'
        f"Content-Type: {_MEDIA_TYPES[name]}\r\n\r\n"
    ).encode("ascii")


def _connection(
    endpoint: str,
    config: GithubUploadConfig,
) -> tuple[http.client.HTTPConnection, str]:
    parsed = urlsplit(endpoint)
    if parsed.hostname is None:
        raise GithubUploadError("invalid_server_url")
    target = urlunsplit(("", "", parsed.path, parsed.query, ""))
    if parsed.scheme == "https":
        context = ssl.create_default_context()
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
    config: GithubUploadConfig,
) -> GithubUploadResponse:
    response = connection.getresponse()
    if connection.sock is not None:
        connection.sock.settimeout(config.response_timeout_seconds)
    body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise GithubUploadError("response_too_large")
    return GithubUploadResponse(
        response.status,
        {name.casefold(): value for name, value in response.getheaders()},
        body,
    )


__all__ = ["StdlibGithubOidcUploadTransport"]
