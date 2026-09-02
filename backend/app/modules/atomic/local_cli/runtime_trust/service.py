"""Pure validation for the host wrapper and sibling-container boundary."""
from __future__ import annotations

import re
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from .models import LocalDockerEndpoint, RuntimeTrustError


_ROOTLESS_SOCKET = re.compile(r"^/run/user/[0-9]+/docker\.sock$")


def parse_local_docker_endpoint(value: str) -> LocalDockerEndpoint:
    """Accept an absolute local Unix socket and reject remote Docker transports."""

    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise RuntimeTrustError("Docker endpoint is invalid") from exc
    if (
        parsed.scheme != "unix"
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise RuntimeTrustError("Docker must use the active local Unix socket")
    decoded = unquote(parsed.path)
    if decoded != parsed.path or "\0" in decoded:
        raise RuntimeTrustError("Docker socket path is not canonical")
    pure = PurePosixPath(decoded)
    if str(pure) != decoded or any(part in {"", ".", ".."} for part in pure.parts[1:]):
        raise RuntimeTrustError("Docker socket path is not canonical")
    return LocalDockerEndpoint(
        raw=value,
        socket_path=Path(decoded),
        rootless=bool(_ROOTLESS_SOCKET.fullmatch(decoded)),
    )


def sibling_snapshot_path(host_run_cache: str, request_id: str) -> Path:
    """Resolve the only host path that may be shared with scanner siblings."""

    try:
        parsed = uuid.UUID(request_id)
    except ValueError as exc:
        raise RuntimeTrustError("request ID must be a canonical UUIDv4") from exc
    if parsed.version != 4 or str(parsed) != request_id:
        raise RuntimeTrustError("request ID must be a canonical UUIDv4")
    if not host_run_cache or "\0" in host_run_cache:
        raise RuntimeTrustError("host run cache is invalid")
    root = PurePosixPath(host_run_cache)
    if (
        not root.is_absolute()
        or str(root) != host_run_cache
        or any(part in {"", ".", ".."} for part in root.parts[1:])
    ):
        raise RuntimeTrustError("host run cache must be an absolute canonical path")
    if root.name != request_id or root.parent.name != "runs":
        raise RuntimeTrustError("host run cache does not match the request ID")
    return Path(str(root / "source"))


__all__ = ["parse_local_docker_endpoint", "sibling_snapshot_path"]
