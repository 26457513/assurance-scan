"""Runtime configuration loaded from environment variables.

Defaults support the canonical local Docker invocation; authenticated hosted
deployments additionally apply account and project-membership boundaries.
"""

from __future__ import annotations

import os
import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.modules.shared.contracts.local_scan import (
    UPLOAD_LIMITS,
    USAGE_LIMITS,
    UploadLimits,
    UsageLimits,
)
from app.modules.atomic.provenance.repository_identity import (
    InvalidRepositoryIdentityError,
    normalize_github_repository_key,
    parse_github_repository,
)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_lower_limit(name: str, maximum: int) -> int:
    value = _env_int(name, maximum)
    if value <= 0 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value for {name}")


def _env_repository_allowlist(name: str) -> frozenset[str]:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return frozenset()
    values = raw.split(",")
    normalized: set[str] = set()
    for value in values:
        if value != value.strip() or not value:
            raise ValueError(f"{name} must contain comma-separated canonical owner/repository values")
        try:
            parsed = parse_github_repository(value)
            if parsed != value:
                raise ValueError
            key = normalize_github_repository_key(value)
        except (InvalidRepositoryIdentityError, ValueError) as exc:
            raise ValueError(
                f"{name} must contain comma-separated canonical owner/repository values"
            ) from exc
        if key in normalized:
            raise ValueError(f"{name} contains a duplicate repository")
        normalized.add(key)
    return frozenset(normalized)


_EMAIL_LOCAL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}")
_EMAIL_DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def normalize_account_email(value: str) -> str:
    """Normalize one conservative Google-account email for rollout matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    local, separator, domain = normalized.partition("@")
    labels = domain.split(".")
    if (
        not separator
        or "@" in domain
        or len(normalized) > 254
        or not _EMAIL_LOCAL.fullmatch(local)
        or len(labels) < 2
        or any(not _EMAIL_DOMAIN_LABEL.fullmatch(label) for label in labels)
    ):
        raise ValueError("invalid account email")
    return normalized


def _env_email_allowlist(name: str) -> frozenset[str]:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return frozenset()
    normalized: set[str] = set()
    for value in raw.split(","):
        if not value or value != value.strip():
            raise ValueError(f"{name} must contain comma-separated account emails")
        try:
            email = normalize_account_email(value)
        except ValueError as exc:
            raise ValueError(f"{name} must contain comma-separated account emails") from exc
        if email in normalized:
            raise ValueError(f"{name} contains a duplicate account email")
        normalized.add(email)
    return frozenset(normalized)


def _env_path(name: str, default: Path) -> Path:
    return Path(_env(name, str(default)))


def account_identity_is_ready(settings: object) -> bool:
    """Return whether account-bound browser and bearer-token features are ready."""
    client_id = getattr(settings, "google_client_id", "")
    client_secret = getattr(settings, "google_client_secret", "")
    session_secret = getattr(settings, "session_secret", "")
    public_base_url = getattr(settings, "public_base_url", "")
    if not all(isinstance(value, str) and value.strip() for value in (client_id, client_secret)):
        return False
    if (
        not isinstance(session_secret, str)
        or len(session_secret) < 32
        or not session_secret.strip()
    ):
        return False
    if not isinstance(public_base_url, str):
        return False
    try:
        parsed = urlsplit(public_base_url)
        port = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname
    secure_origin = parsed.scheme == "https"
    loopback_development_origin = parsed.scheme == "http" and bool(
        hostname and _is_loopback_host(hostname)
    )
    return bool(
        (secure_origin or loopback_development_origin)
        and hostname
        and parsed.username is None
        and parsed.password is None
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and (port is None or 1 <= port <= 65535)
    )


def _is_loopback_host(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Settings:
    """Resolved settings for the running server."""

    # Where the SQLite database lives. Persistent across container restarts
    # when /data is bind-mounted from the host.
    db_path: Path

    # Async SQLAlchemy URL derived from db_path.
    db_url: str

    # Sync URL for Alembic (uses sqlite3 driver, not aiosqlite).
    db_url_sync: str

    # Project root. Set explicitly via ASSURANCE_SCAN_PROJECT_ROOT so the
    # entrypoint can `cd /opt/assurance-scan` (for Python imports) without
    # losing track of where the user's project lives.
    project_root: Path

    # Where the host docker socket lives.
    docker_socket: Path

    # Max parallel scanners within one scan.
    max_concurrent_scanners: int

    # Server bind host/port. 127.0.0.1-only by default.
    host: str
    port: int

    # Logging level.
    log_level: str

    # Shared Basic Auth credentials; unset (default) disables auth.
    app_auth_user: str
    app_auth_password: str

    # Notion standup digest
    notion_token: str
    notion_page_id: str
    notion_orgs: str

    # Bearer token for MCP clients (claude mcp add … --header). Required
    # when auth is on — /mcp never accepts the browser login redirect.
    mcp_token: str

    # Google Workspace login (takes precedence over Basic Auth when set,
    # which stays valid as a fallback for curl etc.).
    google_client_id: str
    google_client_secret: str
    google_domain: str
    session_secret: str
    public_base_url: str
    token_encryption_key: str

    # GitHub CI polling (phase-2 ingest). Poller runs only when both a
    # token and at least one repo are configured.
    poll_repos: tuple[str, ...]
    poll_interval_seconds: int
    github_poll_token: str
    github_org: str

    # Version-one local upload remains closed until explicitly enabled by an
    # operator with account-bound Google/session identity configured.
    scan_token_creation_enabled: bool
    scan_token_creation_user_allowlist: frozenset[str]
    local_ingest_enabled: bool
    local_ingest_repository_allowlist: frozenset[str]
    local_ingest_upload_limits: UploadLimits
    local_ingest_usage_limits: UsageLimits

    # Pre-built, keylessly signed local-CLI release metadata. The application
    # serves these bytes but never creates or signs trust policy at runtime.
    cli_release_manifest_path: str
    cli_release_bundle_path: str


def load_settings() -> Settings:
    """Build a Settings instance from the current environment."""
    db_path = _env_path("ASSURANCE_SCAN_DB_PATH", Path("/data/db.sqlite"))
    project_root = _env_path(
        "ASSURANCE_SCAN_PROJECT_ROOT",
        _env_path("PWD", Path.cwd()),
    )
    return Settings(
        db_path=db_path,
        poll_repos=tuple(r.strip() for r in _env("POLL_REPOS", "").split(",") if r.strip()),
        poll_interval_seconds=_env_int("POLL_INTERVAL_SECONDS", 60),
        github_poll_token=_env("GITHUB_POLL_TOKEN", ""),
        github_org=_env("GITHUB_ORG", ""),
        scan_token_creation_enabled=_env_bool("SCAN_TOKEN_CREATION_ENABLED"),
        scan_token_creation_user_allowlist=_env_email_allowlist(
            "SCAN_TOKEN_CREATION_USER_ALLOWLIST"
        ),
        local_ingest_enabled=_env_bool("LOCAL_INGEST_ENABLED"),
        local_ingest_repository_allowlist=_env_repository_allowlist(
            "LOCAL_INGEST_REPOSITORY_ALLOWLIST"
        ),
        local_ingest_upload_limits=UploadLimits(
            wire_bytes=_env_lower_limit("LOCAL_INGEST_WIRE_BYTES", UPLOAD_LIMITS.wire_bytes),
            parsed_bytes=_env_lower_limit("LOCAL_INGEST_PARSED_BYTES", UPLOAD_LIMITS.parsed_bytes),
            metadata_bytes=_env_lower_limit("LOCAL_INGEST_METADATA_BYTES", UPLOAD_LIMITS.metadata_bytes),
            findings_bytes=_env_lower_limit("LOCAL_INGEST_FINDINGS_BYTES", UPLOAD_LIMITS.findings_bytes),
            sarif_bytes=_env_lower_limit("LOCAL_INGEST_SARIF_BYTES", UPLOAD_LIMITS.sarif_bytes),
            sbom_bytes=_env_lower_limit("LOCAL_INGEST_SBOM_BYTES", UPLOAD_LIMITS.sbom_bytes),
            findings_count=_env_lower_limit("LOCAL_INGEST_FINDINGS_COUNT", UPLOAD_LIMITS.findings_count),
            scanner_results=_env_lower_limit("LOCAL_INGEST_SCANNER_RESULTS", UPLOAD_LIMITS.scanner_results),
            json_depth=_env_lower_limit("LOCAL_INGEST_JSON_DEPTH", UPLOAD_LIMITS.json_depth),
            path_chars=_env_lower_limit("LOCAL_INGEST_PATH_CHARS", UPLOAD_LIMITS.path_chars),
            message_chars=_env_lower_limit("LOCAL_INGEST_MESSAGE_CHARS", UPLOAD_LIMITS.message_chars),
        ),
        local_ingest_usage_limits=UsageLimits(
            uploads_per_token_hour=_env_lower_limit(
                "LOCAL_INGEST_UPLOADS_PER_TOKEN_HOUR", USAGE_LIMITS.uploads_per_token_hour
            ),
            uploads_per_user_day=_env_lower_limit(
                "LOCAL_INGEST_UPLOADS_PER_USER_DAY", USAGE_LIMITS.uploads_per_user_day
            ),
            inflight_per_token=_env_lower_limit("LOCAL_INGEST_INFLIGHT_PER_TOKEN", USAGE_LIMITS.inflight_per_token),
            inflight_per_user=_env_lower_limit("LOCAL_INGEST_INFLIGHT_PER_USER", USAGE_LIMITS.inflight_per_user),
            inflight_per_instance=_env_lower_limit(
                "LOCAL_INGEST_INFLIGHT_PER_INSTANCE", USAGE_LIMITS.inflight_per_instance
            ),
            retained_bytes_per_user=_env_lower_limit(
                "LOCAL_INGEST_RETAINED_BYTES_PER_USER", USAGE_LIMITS.retained_bytes_per_user
            ),
            retained_bytes_per_instance=_env_lower_limit(
                "LOCAL_INGEST_RETAINED_BYTES_PER_INSTANCE", USAGE_LIMITS.retained_bytes_per_instance
            ),
            accepted_bytes_per_user_day=_env_lower_limit(
                "LOCAL_INGEST_ACCEPTED_BYTES_PER_USER_DAY", USAGE_LIMITS.accepted_bytes_per_user_day
            ),
        ),
        cli_release_manifest_path=_env("CLI_RELEASE_MANIFEST_PATH", ""),
        cli_release_bundle_path=_env("CLI_RELEASE_BUNDLE_PATH", ""),
        db_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        db_url_sync=f"sqlite:///{db_path.as_posix()}",
        project_root=project_root,
        docker_socket=_env_path("DOCKER_SOCKET", Path("/var/run/docker.sock")),
        max_concurrent_scanners=_env_int("ASSURANCE_SCAN_PARALLELISM", 4),
        host=_env("ASSURANCE_SCAN_HOST", "127.0.0.1"),
        port=_env_int("ASSURANCE_SCAN_PORT", 8000),
        log_level=_env("ASSURANCE_SCAN_LOG_LEVEL", "INFO"),
        app_auth_user=_env("APP_AUTH_USER", ""),
        app_auth_password=_env("APP_AUTH_PASSWORD", ""),
        mcp_token=_env("MCP_TOKEN", ""),
        notion_token=_env("NOTION_TOKEN", ""),
        notion_page_id=_env("NOTION_PAGE_ID", ""),
        notion_orgs=_env("NOTION_ORGS", ""),
        google_client_id=_env("GOOGLE_CLIENT_ID", ""),
        google_client_secret=_env("GOOGLE_CLIENT_SECRET", ""),
        google_domain=_env("GOOGLE_DOMAIN", "barkleygen.com"),
        session_secret=_env("SESSION_SECRET", ""),
        public_base_url=_env("PUBLIC_BASE_URL", ""),
        token_encryption_key=_env("TOKEN_ENCRYPTION_KEY", ""),
    )


def ensure_db_dir(settings: Settings) -> None:
    """Create the directory holding the SQLite file if missing."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
