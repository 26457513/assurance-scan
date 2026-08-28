"""Secure read, resolution, login, logout, and atomic config persistence."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from .models import CliConfig, ConfigStoreError, ResolvedCliConfig


_KEYS = frozenset(("api_url", "token", "token_label", "installation_id"))


def validate_api_url(value: str, *, allow_insecure_loopback: bool = False) -> str:
    """Return a canonical API origin, rejecting credential-bearing or unsafe URLs."""
    parsed = urlsplit(value.strip())
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigStoreError("API URL must be an origin without credentials, query, or fragment")
    if not parsed.hostname or parsed.path not in ("", "/"):
        raise ConfigStoreError("API URL must be an origin without a path")
    if parsed.scheme == "https":
        pass
    elif parsed.scheme == "http" and allow_insecure_loopback and _is_loopback(parsed.hostname):
        pass
    else:
        raise ConfigStoreError("API URL must use HTTPS")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ConfigStoreError("API URL port is invalid") from exc
    port = f":{parsed_port}" if parsed_port is not None else ""
    return f"{parsed.scheme}://{host}{port}"


def load_config(
    path: Path,
    *,
    expected_uid: int | None = None,
    allow_insecure_loopback: bool = False,
) -> CliConfig:
    """Read an owner-only regular file without following a final symlink."""
    uid = os.getuid() if expected_uid is None else expected_uid
    _validate_directory(path.parent, uid)
    if path.is_symlink():
        raise ConfigStoreError("configuration file must not be a symlink")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ConfigStoreError("configuration file cannot be opened safely") from exc
    try:
        info = os.fstat(fd)
        _validate_file_info(info, uid)
        raw = _read_bounded(fd, 128 * 1024)
    finally:
        os.close(fd)
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ConfigStoreError) as exc:
        raise ConfigStoreError("configuration file is not valid JSON") from exc
    return _parse_config(document, allow_insecure_loopback=allow_insecure_loopback)


def save_config(
    path: Path,
    config: CliConfig,
    *,
    expected_uid: int | None = None,
    allow_insecure_loopback: bool = False,
) -> None:
    """Atomically replace config using a same-directory 0600 temporary file."""
    uid = os.getuid() if expected_uid is None else expected_uid
    _validate_directory(path.parent, uid)
    if path.exists() or path.is_symlink():
        _validate_existing_file(path, uid)
    validated = _parse_config(
        {
            "api_url": config.api_url,
            "installation_id": config.installation_id,
            "token": config.token,
            "token_label": config.token_label,
        },
        allow_insecure_loopback=allow_insecure_loopback,
    )
    payload = (json.dumps(_document(validated), sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=".config.json.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, 0o600)
        _write_all(fd, payload)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if fd >= 0:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        raise


def login_config(
    existing: CliConfig | None,
    *,
    api_url: str,
    token: str,
    token_label: str,
    allow_insecure_loopback: bool = False,
) -> CliConfig:
    """Rotate credentials while preserving the installation identifier."""
    if not token or any(character.isspace() for character in token):
        raise ConfigStoreError("token is invalid")
    label = token_label.strip()
    if not label or len(label) > 64:
        raise ConfigStoreError("token label is invalid")
    installation_id = existing.installation_id if existing else str(uuid.uuid4())
    return CliConfig(
        api_url=validate_api_url(api_url, allow_insecure_loopback=allow_insecure_loopback),
        token=token,
        token_label=label,
        installation_id=installation_id,
    )


def logout_config(config: CliConfig) -> CliConfig:
    """Remove credentials while retaining installation identity and server origin."""
    return CliConfig(api_url=config.api_url, installation_id=config.installation_id)


def resolve_config(
    stored: CliConfig,
    environ: Mapping[str, str],
    *,
    allow_insecure_loopback: bool = False,
) -> ResolvedCliConfig:
    """Apply automation-only URL/token overrides without changing installation identity."""
    url = environ.get("ASSURANCE_SCAN_URL", stored.api_url)
    token = environ.get("ASSURANCE_SCAN_TOKEN", stored.token)
    override = "ASSURANCE_SCAN_URL" in environ or "ASSURANCE_SCAN_TOKEN" in environ
    resolved = CliConfig(
        api_url=validate_api_url(url, allow_insecure_loopback=allow_insecure_loopback),
        token=token,
        token_label=stored.token_label,
        installation_id=stored.installation_id,
    )
    return ResolvedCliConfig(config=resolved, environment_override_used=override)


def _parse_config(document: object, *, allow_insecure_loopback: bool = False) -> CliConfig:
    if not isinstance(document, dict) or set(document) != _KEYS:
        raise ConfigStoreError("configuration fields do not match the v1 contract")
    api_url = document.get("api_url")
    installation_id = document.get("installation_id")
    token = document.get("token")
    token_label = document.get("token_label")
    if not isinstance(api_url, str) or not isinstance(installation_id, str):
        raise ConfigStoreError("configuration fields have invalid types")
    try:
        parsed_id = uuid.UUID(installation_id)
    except ValueError as exc:
        raise ConfigStoreError("installation_id must be a canonical UUIDv4") from exc
    if parsed_id.version != 4 or str(parsed_id) != installation_id:
        raise ConfigStoreError("installation_id must be a canonical UUIDv4")
    if token is not None and not isinstance(token, str):
        raise ConfigStoreError("token has invalid type")
    if token_label is not None and not isinstance(token_label, str):
        raise ConfigStoreError("token_label has invalid type")
    if (token is None) != (token_label is None):
        raise ConfigStoreError("token and token_label must be present together")
    if token is not None and (not token or any(character.isspace() for character in token)):
        raise ConfigStoreError("token is invalid")
    if token_label is not None and (
        not token_label or len(token_label) > 64 or any(ord(character) < 32 for character in token_label)
    ):
        raise ConfigStoreError("token label is invalid")
    return CliConfig(
        api_url=validate_api_url(api_url, allow_insecure_loopback=allow_insecure_loopback),
        token=token,
        token_label=token_label,
        installation_id=installation_id,
    )


def _document(config: CliConfig) -> dict[str, str | None]:
    return {
        "api_url": config.api_url,
        "token": config.token,
        "token_label": config.token_label,
        "installation_id": config.installation_id,
    }


def _validate_directory(path: Path, uid: int) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ConfigStoreError("configuration directory is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ConfigStoreError("configuration directory must not be a symlink")
    if info.st_uid != uid or info.st_mode & 0o077:
        raise ConfigStoreError("configuration directory must be owner-only")


def _validate_existing_file(path: Path, uid: int) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise ConfigStoreError("configuration file must not be a symlink")
    _validate_file_info(info, uid)


def _validate_file_info(info: os.stat_result, uid: int) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
        raise ConfigStoreError("configuration file must be an owner-only regular file")


def _read_bounded(fd: int, maximum: int) -> bytes:
    chunks = bytearray()
    while True:
        chunk = os.read(fd, min(64 * 1024, maximum + 1 - len(chunks)))
        if not chunk:
            return bytes(chunks)
        chunks.extend(chunk)
        if len(chunks) > maximum:
            raise ConfigStoreError("configuration file is too large")


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        offset += os.write(fd, payload[offset:])


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigStoreError("duplicate configuration key")
        result[key] = value
    return result


def _is_loopback(host: str) -> bool:
    import ipaddress

    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


__all__ = [
    "load_config",
    "login_config",
    "logout_config",
    "resolve_config",
    "save_config",
    "validate_api_url",
]
