"""Runtime configuration loaded from environment variables.

Single-user, localhost-only. All defaults assume the canonical
`docker run -v "$PWD:$PWD" -v "$HOME/.assurance-scan:/data"` invocation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_path(name: str, default: Path) -> Path:
    return Path(_env(name, str(default)))


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
