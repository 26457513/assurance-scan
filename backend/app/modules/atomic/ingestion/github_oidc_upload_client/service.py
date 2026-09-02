"""Validate inputs and classify one non-redirecting GitHub OIDC upload attempt."""
from __future__ import annotations

import json
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

from app.modules.shared.contracts.ingest_v2 import ENVELOPE_LIMITS_V2, OIDC_POLICY_V2

from .models import (
    GithubUploadBundle,
    GithubUploadConfig,
    GithubUploadError,
    GithubUploadNetworkError,
    GithubUploadResult,
    GithubUploadTransport,
    JwtInput,
)


_JWT = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RETRYABLE = frozenset((408, 429, 500, 502, 503, 504))
_SUCCESS = frozenset((200, 201, 202))
_PART_FILES = {
    "metadata": "metadata.json",
    "findings": "findings.json",
    "source_contexts": "source-contexts.json",
    "sarif": "results.sarif",
    "sbom": "sbom.cyclonedx.json",
}
_PART_LIMITS = {
    "metadata": ENVELOPE_LIMITS_V2.metadata_bytes,
    "findings": ENVELOPE_LIMITS_V2.findings_bytes,
    "source_contexts": ENVELOPE_LIMITS_V2.source_contexts_bytes,
    "sarif": ENVELOPE_LIMITS_V2.sarif_bytes,
    "sbom": ENVELOPE_LIMITS_V2.sbom_bytes,
}


def read_oidc_jwt(stream: JwtInput) -> str:
    """Read one compact JWT from stdin with no tolerated trailing data."""
    maximum = OIDC_POLICY_V2.maximum_jwt_bytes
    payload = stream.read(maximum + 1)
    if not payload or len(payload) > maximum or b"\x00" in payload:
        raise GithubUploadError("invalid_oidc_input")
    try:
        token = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise GithubUploadError("invalid_oidc_input") from exc
    if not _JWT.fullmatch(token):
        raise GithubUploadError("invalid_oidc_input")
    return token


def load_bundle(root: Path) -> GithubUploadBundle:
    """Load only allowlisted regular files and derive the canonical run identity."""
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise GithubUploadError("invalid_bundle")
    parts: dict[str, Path] = {}
    total = 0
    for name, filename in _PART_FILES.items():
        path = resolved / filename
        if not path.exists():
            if name in {"metadata", "findings", "source_contexts"}:
                raise GithubUploadError("invalid_bundle")
            continue
        size = _regular_size(path)
        if size > _PART_LIMITS[name]:
            raise GithubUploadError("bundle_limit_exceeded")
        total += size
        parts[name] = path
    if total > ENVELOPE_LIMITS_V2.parsed_bytes:
        raise GithubUploadError("bundle_limit_exceeded")
    hash_path = resolved / "envelope.sha256"
    if _regular_size(hash_path) > 65:
        raise GithubUploadError("invalid_bundle")
    payload_hash = hash_path.read_text(encoding="ascii").strip()
    if not _HASH.fullmatch(payload_hash):
        raise GithubUploadError("invalid_bundle")
    idempotency_key = _idempotency_key(parts["metadata"])
    return GithubUploadBundle(resolved, parts, idempotency_key, payload_hash)


def upload_once(
    bundle: GithubUploadBundle,
    config: GithubUploadConfig,
    *,
    transport: GithubUploadTransport,
) -> GithubUploadResult:
    """Make exactly one request; the runner owns fresh-token retry policy."""
    endpoint = _endpoint(config.base_url, config.allow_loopback_http)
    try:
        response = transport.post(endpoint, bundle, config)
    except GithubUploadNetworkError:
        raise
    if response.status in _SUCCESS:
        return GithubUploadResult(response.status, "accepted", False)
    code = _problem_code(response.body, response.status)
    return GithubUploadResult(response.status, code, response.status in _RETRYABLE)


def _idempotency_key(metadata_path: Path) -> str:
    try:
        raw = metadata_path.read_bytes()
        document = json.loads(raw)
        producer = document["producer"]
        if producer["kind"] != "github-actions":
            raise KeyError
        values = tuple(int(producer[name]) for name in ("repository_id", "run_id", "run_attempt"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise GithubUploadError("invalid_bundle") from exc
    if any(value < 1 for value in values):
        raise GithubUploadError("invalid_bundle")
    return ":".join(str(value) for value in values)


def _regular_size(path: Path) -> int:
    try:
        info = path.lstat()
    except OSError as exc:
        raise GithubUploadError("invalid_bundle") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise GithubUploadError("invalid_bundle")
    return info.st_size


def _endpoint(base_url: str, allow_loopback_http: bool) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or not parsed.hostname
    ):
        raise GithubUploadError("invalid_server_url")
    if parsed.scheme == "https":
        pass
    elif parsed.scheme == "http" and allow_loopback_http and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        pass
    else:
        raise GithubUploadError("https_required")
    return f"{parsed.scheme}://{parsed.netloc}/api/v2/ingest/github-actions"


def _problem_code(body: bytes, status: int) -> str:
    if len(body) <= 1024 * 1024:
        try:
            document = json.loads(body)
            code = document.get("code") if isinstance(document, dict) else None
            if isinstance(code, str) and _SAFE_CODE.fullmatch(code):
                return code
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    return f"http_{status}"


__all__ = ["load_bundle", "read_oidc_jwt", "upload_once"]
