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


def load_settings() -> Settings:
    """Build a Settings instance from the current environment."""
    db_path = _env_path("ASSURANCE_SCAN_DB_PATH", Path("/data/db.sqlite"))
    project_root = _env_path(
        "ASSURANCE_SCAN_PROJECT_ROOT",
        _env_path("PWD", Path.cwd()),
    )
    return Settings(
        db_path=db_path,
        db_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        db_url_sync=f"sqlite:///{db_path.as_posix()}",
        project_root=project_root,
        docker_socket=_env_path("DOCKER_SOCKET", Path("/var/run/docker.sock")),
        max_concurrent_scanners=_env_int("ASSURANCE_SCAN_PARALLELISM", 4),
        host=_env("ASSURANCE_SCAN_HOST", "127.0.0.1"),
        port=_env_int("ASSURANCE_SCAN_PORT", 8000),
        log_level=_env("ASSURANCE_SCAN_LOG_LEVEL", "INFO"),
    )


def ensure_db_dir(settings: Settings) -> None:
    """Create the directory holding the SQLite file if missing."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
